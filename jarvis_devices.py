"""
JARVIS device watcher. Speaks (and the HUD shows) when something connects or
disconnects:
  - headsets / earbuds / speakers (audio devices)
  - Bluetooth devices, phones, USB storage, cameras, printers, mouse,
    keyboard, external displays
  - Wi-Fi connect / disconnect / switch
  - charger plugged / unplugged
It also tells jarvis.py when audio hardware changed, so Jarvis re-scans and
starts using the new microphone by itself (no restart).

Windows only. No extra installs: uses built-in PowerShell + netsh, plus psutil.
jarvis.py starts this automatically -- you don't run this file yourself.
"""
import ctypes
import json
import re
import subprocess
import sys
import threading
import time

import psutil

POLL_SECONDS = 4        # how often to look for changes
SETTLE_SECONDS = 1.5    # wait after a change so the device finishes connecting

_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no flashing console windows

PS_CLASSES = "AudioEndpoint,WPD,Camera,Image,DiskDrive,Printer,Mouse,Keyboard,Monitor"  # Bluetooth is read separately
CLASS_LABEL = {
    "AudioEndpoint": "Audio device",
    "Bluetooth": "Bluetooth device",
    "WPD": "Phone or portable device",
    "Camera": "Camera",
    "Image": "Camera or scanner",
    "DiskDrive": "Storage device",
    "Printer": "Printer",
    "Mouse": "Mouse",
    "Keyboard": "Keyboard",
    "Monitor": "Display",
}
_PS = (
    "$ErrorActionPreference='SilentlyContinue';"
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    f"Get-PnpDevice -PresentOnly -Status OK -Class {PS_CLASSES} | "
    "Select-Object Class,FriendlyName | ConvertTo-Json -Compress"
)

_started = False


# ---------- Bluetooth: ask Windows which devices are CONNECTED right now ----------
# (The PnP "Bluetooth" list also contains every paired-but-disconnected device, which is
#  why connect messages used to include devices that weren't connected.)
class _SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint16) for n in ("y", "mo", "dow", "d", "h", "mi", "s", "ms")]


class _BT_INFO(ctypes.Structure):          # BLUETOOTH_DEVICE_INFO
    _fields_ = [("dwSize", ctypes.c_uint32), ("Address", ctypes.c_uint64),
                ("ulClassofDevice", ctypes.c_uint32), ("fConnected", ctypes.c_int32),
                ("fRemembered", ctypes.c_int32), ("fAuthenticated", ctypes.c_int32),
                ("stLastSeen", _SYSTEMTIME), ("stLastUsed", _SYSTEMTIME),
                ("szName", ctypes.c_uint16 * 248)]


class _BT_SEARCH(ctypes.Structure):        # BLUETOOTH_DEVICE_SEARCH_PARAMS
    _fields_ = [("dwSize", ctypes.c_uint32), ("fReturnAuthenticated", ctypes.c_int32),
                ("fReturnRemembered", ctypes.c_int32), ("fReturnUnknown", ctypes.c_int32),
                ("fReturnConnected", ctypes.c_int32), ("fIssueInquiry", ctypes.c_int32),
                ("cTimeoutMultiplier", ctypes.c_ubyte), ("hRadio", ctypes.c_void_p)]


_bt_lib = None
_last_bt = set()


def _bluetooth_connected():
    """Names of Bluetooth devices connected right now, or None if Windows won't tell us."""
    global _bt_lib
    try:
        if _bt_lib is None:
            lib = None
            for dll in ("bthprops.cpl", "irprops.cpl"):
                try:
                    lib = ctypes.WinDLL(dll)       # only exists on Windows
                    break
                except (OSError, AttributeError):
                    continue
            if lib is None:
                return None
            lib.BluetoothFindFirstDeviceW.restype = ctypes.c_void_p
            lib.BluetoothFindFirstDeviceW.argtypes = [ctypes.POINTER(_BT_SEARCH), ctypes.POINTER(_BT_INFO)]
            lib.BluetoothFindNextDevice.restype = ctypes.c_int32
            lib.BluetoothFindNextDevice.argtypes = [ctypes.c_void_p, ctypes.POINTER(_BT_INFO)]
            lib.BluetoothFindDeviceClose.restype = ctypes.c_int32
            lib.BluetoothFindDeviceClose.argtypes = [ctypes.c_void_p]
            _bt_lib = lib
        search = _BT_SEARCH()
        search.dwSize = ctypes.sizeof(search)
        search.fReturnAuthenticated = 1
        search.fReturnRemembered = 1
        search.fReturnConnected = 1
        search.fReturnUnknown = 0
        search.fIssueInquiry = 0               # don't scan the air, just read Windows' own list
        search.cTimeoutMultiplier = 0
        search.hRadio = None
        info = _BT_INFO()
        info.dwSize = ctypes.sizeof(info)
        names = set()
        handle = _bt_lib.BluetoothFindFirstDeviceW(ctypes.byref(search), ctypes.byref(info))
        if not handle:
            return names                       # no Bluetooth devices / no radio
        try:
            while True:
                if info.fConnected:
                    name = bytes(info.szName).decode("utf-16-le", errors="ignore").split("\x00")[0].strip()
                    names.add(name or "unknown device")
                info.dwSize = ctypes.sizeof(info)
                if not _bt_lib.BluetoothFindNextDevice(handle, ctypes.byref(info)):
                    break
        finally:
            _bt_lib.BluetoothFindDeviceClose(handle)
        return names
    except Exception:
        return None


# ---------- snapshots ----------
def _snapshot():
    """Set of (class, name) for everything connected right now, or None if the scan failed."""
    global _last_bt
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS],
                           capture_output=True, timeout=20, creationflags=_NOWIN)
        text = r.stdout.decode("utf-8", errors="replace").strip()
        if not text:
            return None
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        snap = set()
        for d in data:
            cls = (d.get("Class") or "").strip()
            name = (d.get("FriendlyName") or "").strip()
            if cls and name:
                snap.add((cls, name))
        bt = _bluetooth_connected()
        if bt is None:
            bt = _last_bt                      # Windows hiccup: keep the last answer, don't invent changes
        else:
            _last_bt = bt
        for name in bt:
            snap.add(("Bluetooth", name))
        return snap
    except Exception:
        return None


def _wifi_state():
    """SSID if connected, "" if Wi-Fi is up but not connected, None if unknown."""
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True,
                             text=True, timeout=8, creationflags=_NOWIN).stdout
    except Exception:
        return None
    return _parse_wifi(out)


def _parse_wifi(out):
    state = re.search(r"^\s*State\s*:\s*(.+)$", out, re.M)
    ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
    if state and state.group(1).strip().lower() == "connected" and ssid:
        return ssid.group(1).strip()
    return ""


def _plugged():
    """(is_plugged_in, battery_percent) or None on a desktop PC."""
    try:
        b = psutil.sensors_battery()
        return None if b is None else (bool(b.power_plugged), int(b.percent))
    except Exception:
        return None


# ---------- wording ----------
# "HUAWEI FreeBuds 5 Hands-Free" and "HUAWEI FreeBuds 5" are the same earbuds -> say it once.
_SUFFIX = re.compile(r"[\s\-]*(hands[\s\-]?free(\s+ag\s+audio)?|stereo|a2dp)\s*$", re.I)


def _base_name(name):
    return _SUFFIX.sub("", name).strip() or name


def _describe(pairs):
    """[(key, text)] -- one entry per physical device. key is used to avoid repeating yourself."""
    groups, order = {}, []
    for cls, name in sorted(pairs):
        label = CLASS_LABEL.get(cls, cls)
        if cls in ("Mouse", "Keyboard", "Monitor"):
            key, text, prio = cls, label, 0   # names like "HID-compliant mouse" aren't useful aloud
        else:
            shown = name
            if cls == "AudioEndpoint":
                m = re.search(r"\((.+)\)\s*$", name)   # "Headphones (Realme Buds)" -> "Realme Buds"
                shown = m.group(1) if m else name
            shown = _base_name(shown)
            key, text = shown.lower(), f"{label} {shown}"
            prio = 2 if cls == "AudioEndpoint" else 1   # earbuds: "Audio device" beats "Bluetooth device"
        if key not in groups:
            groups[key] = (prio, text)
            order.append(key)
        elif prio > groups[key][0]:
            groups[key] = (prio, text)
    return [(k, groups[k][1]) for k in order]


def _sentence(items, verb):
    text = " and ".join(items[:3])
    if len(items) > 3:
        text += f" and {len(items) - 3} more"
    return f"{text} {verb}, sir."


def _wifi_message(old, new):
    if old is None or new is None or old == new:
        return None
    if new == "":
        return f"Wi-Fi disconnected from {old}, sir."
    if old == "":
        return f"Wi-Fi connected to {new}, sir."
    return f"Wi-Fi switched to {new}, sir."


# ---------- the watcher thread ----------
def _say(speak, text):
    try:
        speak(text)
    except Exception as e:
        print(f"(device announcement failed: {e})")


DEDUP_SECONDS = 10      # same device + same event within this time is only announced once


def _announce(speak, items, verb, recent):
    now = time.time()
    fresh = []
    for key, text in items:
        if now - recent.get((verb, key), 0) < DEDUP_SECONDS:
            continue                           # e.g. Bluetooth entry arrived first, audio entry a moment later
        recent[(verb, key)] = now
        fresh.append(text)
    if fresh:
        _say(speak, _sentence(fresh, verb))


def _watch(speak, on_audio_change):
    base = _snapshot()
    wifi = _wifi_state()
    plug = _plugged()
    recent = {}
    while True:
        time.sleep(POLL_SECONDS)
        try:
            # --- hardware ---
            new = _snapshot()
            if base is None:
                base = new
            elif new is not None and new != base:
                time.sleep(SETTLE_SECONDS)
                settled = _snapshot()
                if settled is not None:
                    new = settled
                added, removed = new - base, base - new
                base = new
                _announce(speak, _describe(added), "connected", recent)
                _announce(speak, _describe(removed), "disconnected", recent)
                if on_audio_change and any(c == "AudioEndpoint" for c, _ in added | removed):
                    time.sleep(1.0)           # give Windows a moment to pick its new default mic
                    on_audio_change()

            # --- Wi-Fi ---
            w = _wifi_state()
            msg = _wifi_message(wifi, w)
            if w is not None:
                wifi = w
            if msg:
                _say(speak, msg)

            # --- charger ---
            p = _plugged()
            if p is not None and plug is not None and p[0] != plug[0]:
                state = "connected" if p[0] else "disconnected"
                _say(speak, f"Charger {state}, battery at {p[1]} percent, sir.")
            if p is not None:
                plug = p
        except Exception as e:
            print(f"(device watcher hiccup: {e})")


def start(speak, on_audio_change=None):
    """Start the background watcher. speak(text) is called for each announcement."""
    global _started
    if _started:
        return None
    if sys.platform != "win32":
        print("(device announcements are Windows-only -- skipping)")
        return None
    _started = True
    t = threading.Thread(target=_watch, args=(speak, on_audio_change), daemon=True)
    t.start()
    return t
