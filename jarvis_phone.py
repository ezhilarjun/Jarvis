"""
JARVIS phone control (via ADB -- Android Debug Bridge).
Lets you command your Android phone by voice through Jarvis on your laptop.

SETUP:
  1. Phone: Settings > About phone > tap "Build number" 7 times (unlocks
     Developer Options). Then Settings > Developer Options > USB debugging: ON.
  2. Connect phone to laptop via USB cable. Tap "Allow" on the phone's
     USB debugging popup.
  3. Laptop: download "SDK Platform-Tools" from
     https://developer.android.com/tools/releases/platform-tools
     Extract to C:\\platform-tools and add that folder to your PATH.
  4. Test:  adb devices   -- should list your phone.

SECURITY NOTE: Unlocking with a PIN means Jarvis knows your PIN in plain
text in this file. Only set PHONE_PIN below if you accept that risk, or
leave it blank and just use phone_wake() + fingerprint/face unlock.

Run (adds phone tools on top of jarvis_apps.py):
  python jarvis_phone.py
"""
import subprocess
import time

import jarvis

try:
    import jarvis_apps  # noqa: F401  (brings in desktop + web tools too)
except ImportError:
    try:
        import jarvis_desktop  # noqa: F401
    except ImportError:
        pass

# Leave blank ("") to skip PIN auto-entry and just wake the screen.
PHONE_PIN = ""

jarvis.SYSTEM += (
    " You can also control the user's Android phone via ADB tools: "
    "phone_wake, phone_unlock, phone_open_app, phone_list_apps, phone_home, "
    "phone_back, phone_screenshot, phone_type_text, phone_tap, phone_swipe."
)


def _adb(*args, timeout=15):
    try:
        r = subprocess.run(["adb"] + list(args), capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return "ADB not found. Install platform-tools and add it to PATH."
    except subprocess.TimeoutExpired:
        return "Phone command timed out (is it connected?)."


def _connected():
    out = _adb("devices")
    lines = [l for l in out.splitlines() if l.strip() and "List of devices" not in l]
    return any("\tdevice" in l for l in lines)


def phone_wake():
    if not _connected():
        return "No phone connected. Check USB cable and USB debugging."
    _adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
    time.sleep(0.5)
    _adb("shell", "input", "swipe", "500", "1500", "500", "500")  # swipe up
    return "Phone screen woken."


def phone_unlock():
    msg = phone_wake()
    if "connected" in msg.lower() and "No phone" in msg:
        return msg
    if not PHONE_PIN:
        return "Screen woken. Set PHONE_PIN in jarvis_phone.py to auto-enter a PIN, or unlock manually (fingerprint/face)."
    time.sleep(0.5)
    _adb("shell", "input", "text", PHONE_PIN)
    _adb("shell", "input", "keyevent", "KEYCODE_ENTER")
    return "Phone unlocked."


def phone_home():
    _adb("shell", "input", "keyevent", "KEYCODE_HOME")
    return "Went to home screen."


def phone_back():
    _adb("shell", "input", "keyevent", "KEYCODE_BACK")
    return "Pressed back."


def phone_list_apps():
    out = _adb("shell", "pm", "list", "packages", "-3")  # third-party (user-installed) apps
    pkgs = [l.replace("package:", "") for l in out.splitlines() if l.startswith("package:")]
    return ", ".join(pkgs[:40]) + (f" ... and {len(pkgs)-40} more" if len(pkgs) > 40 else "")


# Common app name -> Android package name shortcuts. Add more as needed;
# for anything else, use the exact package name from phone_list_apps.
KNOWN_APPS = {
    "whatsapp": "com.whatsapp",
    "youtube": "com.google.android.youtube",
    "chrome": "com.android.chrome",
    "gmail": "com.google.android.gm",
    "instagram": "com.instagram.android",
    "camera": "com.android.camera",
    "settings": "com.android.settings",
    "spotify": "com.spotify.music",
}


def phone_open_app(name):
    pkg = KNOWN_APPS.get(name.lower(), name)  # allow raw package names too
    result = _adb("shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1")
    if "No activities found" in result or "Error" in result:
        return f"Could not open '{name}'. Use phone_list_apps to find the exact package name."
    return f"Opened {name} on your phone."


def phone_screenshot():
    remote = "/sdcard/jarvis_phone_shot.png"
    import os
    local = os.path.join(os.path.expanduser("~"), "Pictures", "jarvis_phone_shot.png")
    _adb("shell", "screencap", "-p", remote)
    _adb("pull", remote, local)
    return f"Saved phone screenshot to {local}"


def phone_type_text(text):
    safe = text.replace(" ", "%s")
    _adb("shell", "input", "text", safe)
    return "Typed on phone."


def phone_tap(x, y):
    _adb("shell", "input", "tap", str(int(x)), str(int(y)))
    return f"Tapped phone at {x},{y}"


def phone_swipe(x1, y1, x2, y2):
    _adb("shell", "input", "swipe", str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)))
    return "Swiped on phone."


NEW_TOOLS = {
    "phone_wake": (phone_wake, "{}  -- Wake the phone screen."),
    "phone_unlock": (phone_unlock, "{}  -- Wake and unlock the phone (needs PHONE_PIN set, or fingerprint/face manually)."),
    "phone_home": (phone_home, "{}  -- Go to phone home screen."),
    "phone_back": (phone_back, "{}  -- Press phone back button."),
    "phone_list_apps": (phone_list_apps, "{}  -- List installed apps on the phone."),
    "phone_open_app": (phone_open_app, '{"name": str}  -- Open an app on the phone by name or package.'),
    "phone_screenshot": (phone_screenshot, "{}  -- Save a screenshot of the phone to this PC."),
    "phone_type_text": (phone_type_text, '{"text": str}  -- Type text into the focused field on the phone.'),
    "phone_tap": (phone_tap, '{"x": num, "y": num}  -- Tap a point on the phone screen.'),
    "phone_swipe": (phone_swipe, '{"x1": num, "y1": num, "x2": num, "y2": num}  -- Swipe on the phone screen.'),
}

for name, (fn, desc) in NEW_TOOLS.items():
    jarvis.register_tool(name, fn, desc)

if __name__ == "__main__":
    jarvis.main()
