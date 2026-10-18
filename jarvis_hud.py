"""
JARVIS HUD -- Iron Man peeks in from the right edge of your screen, says everything
Jarvis says (typed out while Jarvis speaks), then slides away again.

Run this file -- it starts Jarvis and every extension for you:

    py -3.12 jarvis_hud.py

Needs ironman.png in the same folder (included). To use your own picture, replace it
with a PNG that has a transparent background (a plain black background works too).
Windows only for the see-through effect; no extra installs (uses tkinter, Pillow, numpy).
"""
import ctypes
import math
import os
import queue
import random
import textwrap
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

import psutil

import jarvis

# ---- load whichever extensions are present (phone -> apps -> desktop chain, then the welcome routine) ----
for _name in ("jarvis_phone", "jarvis_apps", "jarvis_desktop"):
    try:
        __import__(_name)
        break
    except ImportError:
        continue
try:
    import jarvis_welcome  # noqa: F401  ("Jarvis, wake up" routine)
except ImportError:
    pass
except Exception as _e:
    print(f"(jarvis_welcome could not load: {_e})")

# ---------- settings ----------
IMAGE_FILE = "ironman.png"
PANEL_WIDTH = 440            # width of the speech panel (pixels at 100% scaling)
HIDE_DELAY = 4.0             # seconds Iron Man stays after he finishes talking
PTT_RELEASE_TIMEOUT = 6.0    # if you let go of the talk key and nothing is heard, leave after this long
TYPE_SECONDS_PER_CHAR = 0.04 # typing speed of the reply text
SLIDE_IN = 0.7               # seconds
SLIDE_OUT = 0.55

KEY = "#010203"              # this exact colour becomes see-through
CYAN = "#28d2ff"
CYAN_BRIGHT = "#bdf4ff"
CYAN_DIM = "#145a73"
PANEL_BG = "#06141d"
PANEL_EDGE = "#1f8fb3"
TEXT = "#d6f4ff"
DIM = "#6f9bb0"
GREEN = "#36e06a"
AMBER = "#ffb020"

# where things are on the picture, as fractions of its width/height
REACTOR = (0.242, 0.874, 0.073)               # chest reactor: x, y, radius (fraction of width)
EYES = [(0.223, 0.304, 0.182, 0.020), (0.693, 0.290, 0.198, 0.027)]  # x, y, glint width, glint height

# ---------- connect to Jarvis (speak / listen events) ----------
_q = queue.Queue()
_orig_speak = jarvis.speak
_orig_listen = jarvis.listen


def _hooked_speak(text):
    _q.put(("jarvis", text))
    try:
        _orig_speak(text)
    finally:
        _q.put(("done", None))


def _hooked_listen():
    text = _orig_listen()
    if text:
        _q.put(("you", text))
    return text


jarvis.speak = _hooked_speak
jarvis.listen = _hooked_listen


# ---------- small helpers ----------
def _ease_out(t):
    return 1 - (1 - t) ** 3


def _ease_in(t):
    return t ** 3


def _mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _work_area(root):
    """(left, top, right, bottom) of the screen without the taskbar."""
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
        rc = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rc), 0):  # SPI_GETWORKAREA
            return rc.l, rc.t, rc.r, rc.b
    except Exception:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight() - 48


def _heard_wake_word(text):
    f = getattr(jarvis, "has_wake", None)
    return f(text) if f else getattr(jarvis, "WAKE_WORD", "jarvis") in text.lower()


def _uses_push_to_talk():
    f = getattr(jarvis, "_use_ptt", None)
    return bool(f()) if f else False


class Hud:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("JARVIS")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=KEY)
        try:
            self.root.wm_attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass                                   # only Windows can make a colour see-through

        self.ui = max(1.0, self.root.winfo_fpixels("1i") / 96.0)   # screen scaling (125%, 150% ...)
        ui = self.ui
        left, top, right, bottom = _work_area(self.root)
        self.H = max(500, bottom - top)

        self.fig_photo, self.fw, self.fh = self._load_figure(int(self.H * 0.98))
        self.panel_w = int(PANEL_WIDTH * ui)
        self.pad = int(14 * ui)
        self.W = self.fw + self.panel_w + self.pad * 2 + int(12 * ui)
        self.root.geometry(f"{self.W}x{self.H}+{right - self.W}+{top}")

        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H, bg=KEY, highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", lambda e: self._begin_leave())   # click the panel to dismiss
        self._no_focus_stealing()

        self.f_title = tkfont.Font(family="Consolas", size=13, weight="bold")
        self.f_text = tkfont.Font(family="Consolas", size=12)
        self.f_small = tkfont.Font(family="Consolas", size=9)
        self.f_label = tkfont.Font(family="Consolas", size=9, weight="bold")
        self.f_clock = tkfont.Font(family="Consolas", size=26, weight="bold")

        self.state = "hidden"        # hidden | entering | shown | leaving
        self.t0 = 0.0
        self.off = 0.0               # horizontal shift: 0 = fully in view, W = hidden past the right edge
                                     # (the scene is built at 0, then pushed off-screen below)
        self.status = "STANDBY"
        self.user_text = ""
        self.reply_full = ""
        self.type_t0 = 0.0
        self.speaking = False
        self.key_down = False
        self.hide_at = None
        self.bars = [0.08] * 26
        self._cache = {}
        self._last_sys = 0.0

        self._build_scene()
        self._set_offset(self.W)
        self.root.withdraw()
        self.root.after(33, self._tick)
        self.root.after(40, self._poll)

    # ---------- picture ----------
    def _load_figure(self, target_h):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), IMAGE_FILE)
        try:
            import numpy as np
            from PIL import Image, ImageTk
            im = Image.open(path).convert("RGBA")
            arr = np.asarray(im)
            if arr[..., 3].min() == 255:           # no transparency in the file: treat near-black as background
                arr = arr.copy()
                arr[..., 3] = np.where(arr[..., :3].max(axis=2) < 14, 0, 255)
                im = Image.fromarray(arr, "RGBA")
            w = max(1, int(im.width * target_h / im.height))
            im = im.resize((w, target_h), Image.LANCZOS)       # resizes colour + transparency together
            arr = np.asarray(im)
            solid = arr[..., 3] >= 128                          # crisp edge, no dark halo
            out = np.empty(arr.shape[:2] + (3,), dtype="uint8")
            out[:] = (1, 2, 3)                                  # the see-through colour
            out[solid] = arr[..., :3][solid]
            clash = solid & (out[..., 0] == 1) & (out[..., 1] == 2) & (out[..., 2] == 3)
            out[clash] = (2, 3, 4)
            return ImageTk.PhotoImage(Image.fromarray(out, "RGB")), w, target_h
        except Exception as e:
            print(f"(HUD picture '{IMAGE_FILE}' could not be loaded: {e} -- using a simple orb instead)")
            return None, int(target_h * 0.30), target_h

    def _no_focus_stealing(self):
        """Don't grab keyboard focus and don't show up in Alt-Tab (Windows)."""
        try:
            self.root.update_idletasks()
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            style = user32.GetWindowLongW(hwnd, -20)                       # GWL_EXSTYLE
            user32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x80)    # NOACTIVATE | TOOLWINDOW
        except Exception:
            pass

    # ---------- scene ----------
    def _panel(self, x, y, w, h, tag="ui"):
        c = self.canvas
        k = 16 * self.ui
        pts = [x + k, y, x + w, y, x + w, y + h - k, x + w - k, y + h, x, y + h, x, y + k]
        c.create_polygon(pts, fill=PANEL_BG, outline=PANEL_EDGE, width=2, tags=tag)
        c.create_line(x + k, y + 5, x + w - 40 * self.ui, y + 5, fill=CYAN, width=2, tags=tag)   # bright top edge

    def _build_scene(self):
        c, ui, W, H = self.canvas, self.ui, self.W, self.H

        # left rail with tick marks
        rail_x = 3
        c.create_line(rail_x, H * 0.06, rail_x, H * 0.94, fill=CYAN_DIM, width=2, tags="ui")
        y, i = H * 0.06, 0
        while y < H * 0.94:
            c.create_line(rail_x, y, rail_x + (16 if i % 5 == 0 else 8) * ui, y, fill=CYAN_DIM, tags="ui")
            y += 28 * ui
            i += 1

        # ----- speech panel -----
        px, py, pw = self.pad + int(12 * ui), int(H * 0.14), self.panel_w
        lh = self.f_text.metrics("linespace")
        self.you_lines, self.reply_lines = 3, 9
        self.cpl = max(16, int((pw - 32 * ui) / max(1, self.f_text.measure("M"))))   # characters per line

        y_title = py + 24 * ui
        eq_top = py + 56 * ui
        eq_h = 26 * ui
        y_you_label = eq_top + eq_h + 14 * ui
        y_you_text = y_you_label + 14 * ui
        y_sep2 = y_you_text + self.you_lines * lh + 8 * ui
        y_rep_label = y_sep2 + 12 * ui
        y_rep_text = y_rep_label + 14 * ui
        ph = int(y_rep_text + self.reply_lines * lh + 16 * ui - py)
        self._panel(px, py, pw, ph)

        c.create_text(px + 16 * ui, y_title, text="J.A.R.V.I.S", anchor="w", fill=CYAN, font=self.f_title, tags="ui")
        self.status_dot = c.create_oval(px + pw - 26 * ui, y_title - 5 * ui, px + pw - 16 * ui, y_title + 5 * ui,
                                        fill=DIM, outline="", tags="ui")
        self.status_txt = c.create_text(px + pw - 34 * ui, y_title, text="STANDBY", anchor="e", fill=DIM,
                                        font=self.f_label, tags="ui")
        c.create_line(px + 12 * ui, py + 46 * ui, px + pw - 12 * ui, py + 46 * ui, fill=PANEL_EDGE, tags="ui")

        # equalizer bars (move while Jarvis talks)
        n = len(self.bars)
        bw = (pw - 32 * ui) / n
        self.bar_items, self.bar_base = [], []
        for k in range(n):
            x = px + 16 * ui + k * bw
            self.bar_base.append((x, eq_top + eq_h, bw - 2 * ui))
            self.bar_items.append(c.create_rectangle(0, 0, 0, 0, fill=CYAN, outline="", tags="dyn"))

        c.create_text(px + 16 * ui, y_you_label, text="YOU", anchor="w", fill=DIM, font=self.f_label, tags="ui")
        self.you_item = c.create_text(px + 16 * ui, y_you_text, text="", anchor="nw", fill=DIM, font=self.f_text,
                                      width=pw - 32 * ui, tags="ui")
        c.create_line(px + 12 * ui, y_sep2, px + pw - 12 * ui, y_sep2, fill=PANEL_EDGE, tags="ui")
        c.create_text(px + 16 * ui, y_rep_label, text="JARVIS", anchor="w", fill=CYAN, font=self.f_label, tags="ui")
        self.reply_item = c.create_text(px + 16 * ui, y_rep_text, text="", anchor="nw", fill=TEXT, font=self.f_text,
                                        width=pw - 32 * ui, tags="ui")

        # ----- system panel -----
        sy = py + ph + 16 * ui
        sh = 170 * ui
        self._panel(px, sy, pw, sh)
        c.create_text(px + 16 * ui, sy + 22 * ui, text="SYSTEM", anchor="w", fill=CYAN, font=self.f_label, tags="ui")
        self.clock_item = c.create_text(px + 16 * ui, sy + 58 * ui, text="", anchor="w", fill=TEXT,
                                        font=self.f_clock, tags="ui")
        self.date_item = c.create_text(px + 16 * ui, sy + 88 * ui, text="", anchor="w", fill=DIM,
                                       font=self.f_small, tags="ui")
        self.bat_item = c.create_text(px + pw - 16 * ui, sy + 58 * ui, text="", anchor="e", fill=GREEN,
                                      font=self.f_label, tags="ui")
        self.meters = []
        for j, label in enumerate(("CPU", "RAM")):
            my = sy + (116 + j * 22) * ui
            c.create_text(px + 16 * ui, my, text=label, anchor="w", fill=DIM, font=self.f_label, tags="ui")
            x0, x1 = px + 60 * ui, px + pw - 70 * ui
            c.create_rectangle(x0, my - 5 * ui, x1, my + 5 * ui, outline=PANEL_EDGE, tags="ui")
            fill = c.create_rectangle(0, 0, 0, 0, fill=CYAN, outline="", tags="dyn")
            pct = c.create_text(px + pw - 16 * ui, my, text="", anchor="e", fill=TEXT, font=self.f_small, tags="ui")
            self.meters.append((fill, x0, x1, my, pct))

        # ----- Iron Man (or a plain orb if the picture is missing) -----
        if self.fig_photo is not None:
            self.fig_x, self.fig_y = W - self.fw, H - self.fh
            self.fig_item = c.create_image(0, 0, image=self.fig_photo, anchor="nw", tags="fig")
            self.reactor = (self.fig_x + REACTOR[0] * self.fw, self.fig_y + REACTOR[1] * self.fh)
            self.r0 = REACTOR[2] * self.fw
            eyes = [(self.fig_x + ex * self.fw, self.fig_y + ey * self.fh, gw * self.fw * 0.55,
                     max(gh * self.fh * 1.1, 8 * ui)) for ex, ey, gw, gh in EYES]
        else:
            self.fig_item = None
            self.reactor = (W - 110 * ui, H * 0.60)
            self.r0 = 36 * ui
            eyes = []
            c.create_oval(self.reactor[0] - self.r0, self.reactor[1] - self.r0, self.reactor[0] + self.r0,
                          self.reactor[1] + self.r0, fill=CYAN_BRIGHT, outline=CYAN, width=3, tags="ui")
        self.rings = [c.create_oval(0, 0, 0, 0, outline=CYAN, width=2, tags="dyn") for _ in range(3)]
        self.eyes = [(ex, ey, rx, ry,
                      c.create_oval(0, 0, 0, 0, outline=CYAN, width=1, tags="dyn"),
                      c.create_oval(0, 0, 0, 0, outline=CYAN_BRIGHT, width=2, tags="dyn")) for ex, ey, rx, ry in eyes]
        c.tag_raise("dyn")

    # ---------- slide in / out ----------
    def _set_offset(self, off):
        dx = off - self.off
        if dx:
            self.canvas.move("ui", dx, 0)
        self.off = off
        if self.fig_item is not None:
            bob = 2 * math.sin(time.time() * 1.6) * self.ui if self.state == "shown" else 0
            self.canvas.coords(self.fig_item, self.fig_x + off, self.fig_y + bob)

    def _show(self):
        if self.state == "hidden":
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.state = "entering"
            self.t0 = time.time()
        elif self.state == "leaving":                      # changed his mind: come back from where he is
            u = 1 - (self.off / self.W) ** (1 / 3) if self.off > 0 else 1.0
            self.state = "entering"
            self.t0 = time.time() - SLIDE_IN * u

    def _begin_leave(self):
        if self.state in ("entering", "shown"):
            u = (self.off / self.W) ** (1 / 3) if self.off > 0 else 0.0
            self.state = "leaving"
            self.t0 = time.time() - SLIDE_OUT * u

    def _finish_hide(self):
        self._set_offset(self.W)
        self.root.withdraw()
        self.state = "hidden"
        self.status = "STANDBY"
        self.user_text = self.reply_full = ""
        self.speaking = False
        self.hide_at = None

    # ---------- events from Jarvis ----------
    def _poll(self):
        try:
            while True:
                kind, payload = _q.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self.root.after(40, self._poll)

    def _handle(self, kind, payload):
        now = time.time()
        if kind == "you":
            if _uses_push_to_talk() or self.state in ("entering", "shown") or _heard_wake_word(payload):
                self._show()
                self.user_text = payload
                self.reply_full = ""
                self.status = "THINKING"
                self.hide_at = None
        elif kind == "jarvis":
            self._show()
            self.reply_full = payload
            self.type_t0 = now
            self.status = "SPEAKING"
            self.speaking = True
            self.hide_at = None
        elif kind == "done":
            self.speaking = False
            self.type_t0 = min(self.type_t0, now - len(self.reply_full) * TYPE_SECONDS_PER_CHAR)  # finish typing
            self.status = "STANDBY"
            self.hide_at = now + HIDE_DELAY
        elif kind == "exit":
            self.root.after(1500, self.root.destroy)

    def _check_key(self, now):
        """Iron Man appears the moment you hold the talk key."""
        kb = getattr(jarvis, "keyboard", None)
        if kb is None or not getattr(jarvis, "PUSH_TO_TALK", False):
            return
        try:
            fn = getattr(jarvis, "ptt_pressed", None)       # knows about the Copilot key
            down = fn() if fn is not None else kb.is_pressed(jarvis.PTT_KEY)
        except Exception:
            return
        if down and not self.key_down:
            self.key_down = True
            self._show()
            self.status = "LISTENING"
            self.user_text = self.reply_full = ""
            self.hide_at = None
        elif not down and self.key_down:
            self.key_down = False
            if self.status == "LISTENING":
                self.status = "THINKING"
            self.hide_at = now + PTT_RELEASE_TIMEOUT

    # ---------- animation ----------
    def _tick(self):
        now = time.time()
        self._check_key(now)
        if self.state == "entering":
            u = (now - self.t0) / SLIDE_IN
            if u >= 1:
                u, self.state = 1.0, "shown"
            self._set_offset(self.W * (1 - _ease_out(u)))
        elif self.state == "leaving":
            u = (now - self.t0) / SLIDE_OUT
            if u >= 1:
                self._finish_hide()
            else:
                self._set_offset(self.W * _ease_in(u))
        elif self.state == "shown":
            self._set_offset(0.0)
            if self.hide_at and now >= self.hide_at and not self.key_down and not self.speaking:
                self._begin_leave()
        if self.state != "hidden":
            self._render(now)
        self.root.after(33, self._tick)

    def _wrap(self, text, lines, tail):
        rows = []
        for para in text.split("\n"):
            rows += textwrap.wrap(para, self.cpl) or [""]
        if len(rows) > lines:
            rows = (["..."] + rows[-(lines - 1):]) if tail else (rows[:lines - 1] + [rows[lines - 1] + "..."])
        return "\n".join(rows)

    def _set_text(self, item, text):
        if self._cache.get(item) != text:
            self._cache[item] = text
            self.canvas.itemconfig(item, text=text)

    def _render(self, now):
        c, ui, off = self.canvas, self.ui, self.off

        # status line
        label, color = {"LISTENING": ("LISTENING", GREEN), "THINKING": ("THINKING", AMBER),
                        "SPEAKING": ("SPEAKING", CYAN)}.get(self.status, ("STANDBY", DIM))
        c.itemconfig(self.status_txt, text=label, fill=color)
        c.itemconfig(self.status_dot, fill=color)

        # typed-out text
        shown = int((now - self.type_t0) / TYPE_SECONDS_PER_CHAR) if self.reply_full else 0
        part = self.reply_full[:shown]
        if shown < len(self.reply_full):
            part += "_"
        self._set_text(self.reply_item, self._wrap(part, self.reply_lines, tail=True))
        self._set_text(self.you_item, self._wrap(self.user_text, self.you_lines, tail=False))

        # equalizer
        for k, item in enumerate(self.bar_items):
            if self.status == "SPEAKING":
                target = random.uniform(0.15, 1.0)
            elif self.status == "LISTENING":
                target = random.uniform(0.1, 0.55)
            else:
                target = 0.06
            self.bars[k] += (target - self.bars[k]) * 0.35
            x, y_bottom, w = self.bar_base[k]
            h = max(2 * ui, self.bars[k] * 26 * ui)
            c.coords(item, x + off, y_bottom - h, x + off + w, y_bottom)

        # arc-reactor rings and eye glow
        speed = {"SPEAKING": 1.3, "LISTENING": 1.8, "THINKING": 0.9}.get(self.status, 0.35)
        cx, cy = self.reactor[0] + off, self.reactor[1]
        for k, ring in enumerate(self.rings):
            ph = (now * speed + k / len(self.rings)) % 1.0
            r = self.r0 * (1.15 + 1.6 * ph)
            c.coords(ring, cx - r, cy - r, cx + r, cy + r)
            c.itemconfig(ring, outline=_mix(CYAN_BRIGHT, CYAN_DIM, ph), state="hidden" if ph > 0.93 else "normal")
        pulse = 0.5 + 0.5 * math.sin(now * (8 if self.status == "SPEAKING" else 2.5))
        for ex, ey, rx, ry, outer, inner in self.eyes:
            ex += off
            k = 1.0 + 0.18 * pulse
            c.coords(inner, ex - rx * k, ey - ry * k, ex + rx * k, ey + ry * k)
            c.coords(outer, ex - rx * k * 1.3, ey - ry * k * 1.7, ex + rx * k * 1.3, ey + ry * k * 1.7)

        # clock + meters (once a second)
        if now - self._last_sys >= 1.0:
            self._last_sys = now
            self._set_text(self.clock_item, time.strftime("%I:%M:%S %p"))
            self._set_text(self.date_item, time.strftime("%A, %d %B %Y").upper())
            try:
                bat = psutil.sensors_battery()
                self._set_text(self.bat_item,
                               f"BAT {int(bat.percent)}%{' +' if bat.power_plugged else ''}" if bat else "AC POWER")
                self._pct = (psutil.cpu_percent(), psutil.virtual_memory().percent)
            except Exception:
                self._pct = getattr(self, "_pct", (0, 0))
        pcts = getattr(self, "_pct", (0, 0))
        for (fill, x0, x1, my, pct_item), value in zip(self.meters, pcts):
            c.coords(fill, x0 + off, my - 4 * ui, x0 + off + (x1 - x0) * value / 100.0, my + 4 * ui)
            self._set_text(pct_item, f"{value:.0f}%")

    def run(self):
        self.root.mainloop()


def _run_backend():
    try:
        jarvis.main()
    finally:
        _q.put(("exit", None))


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # crisp on 125%/150% screens
    except Exception:
        pass
    threading.Thread(target=_run_backend, daemon=True).start()
    Hud().run()
