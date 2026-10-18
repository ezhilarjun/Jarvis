"""
JARVIS HUD PRO - a glowing, animated, see-through overlay for your whole screen.

What you see when you talk to Jarvis (hold the talk key, or say "Jarvis"):
  * a glowing orb with rotating rings and a waveform ring that moves with your voice
      green = LISTENING, amber = THINKING, cyan = SPEAKING
  * a glass panel that shows what you said and types out Jarvis's reply
  * clock, date, CPU / RAM / battery meters and glowing screen-corner brackets
It fades in, and fades away a few seconds after Jarvis finishes. It never takes focus
and you can click straight through it.

Setup (one time):   py -3.12 -m pip install PySide6
Run:                py -3.12 jarvis_hud_pro.py        (starts Jarvis + every extension too)

Windows only for the see-through overlay. Change the look with the settings below.
"""
import math
import os
import queue
import random
import re
import sys
import threading
import time

import psutil

# Windows prints a harmless "SetProcessDpiAwarenessContext() failed" notice when another library
# (pygame) already set the screen-scaling mode. Hide it so it doesn't look like an error.
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")

try:
    from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
    from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QGuiApplication, QLinearGradient,
                               QPainter, QPainterPath, QPen, QPixmap, QRadialGradient)
    from PySide6.QtWidgets import QApplication, QWidget
except ImportError:
    print("This HUD needs PySide6. Install it with:   py -3.12 -m pip install PySide6")
    sys.exit(1)

def _already_running():
    """True if another Jarvis HUD is already running (stops a double start from login + a double-click)."""
    import socket
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 47831))
        sock.listen(1)
    except OSError:
        return True
    globals()["_lock_socket"] = sock          # keep it open for as long as we run
    return False


if __name__ == "__main__" and _already_running():
    print("Jarvis is already running - not starting a second copy.")
    sys.exit(0)

import jarvis

# ---------------------------------------------------------------- settings
HIDE_DELAY = 8.0          # seconds the HUD stays after Jarvis finishes talking
PTT_RELEASE_TIMEOUT = 8.0  # if you let go of the talk key and nothing is understood, hide after this long
SCALE = 1.0               # overall size (1.3 = bigger, 0.8 = smaller)
DIM_SCREEN = 0.22         # darkens the screen edges so the HUD stands out (0 = off, 0.4 = strong)
FPS = 30                  # animation smoothness (lower it if your PC feels slow)
TYPE_CPS = 40             # how fast Jarvis's reply is typed out (characters per second)
SHOW_CLOCK = True
SHOW_STATS = True
SHOW_CORNERS = True

FONT_HEAD = "Bahnschrift"  # techy headings (ships with Windows 10/11)
FONT_BODY = "Segoe UI"

C_CYAN = (40, 210, 255)
C_GREEN = (60, 255, 170)
C_AMBER = (255, 176, 40)
C_SPEAK = (90, 232, 255)
STATE_COLOR = {"STANDBY": C_CYAN, "LISTENING": C_GREEN, "THINKING": C_AMBER, "SPEAKING": C_SPEAK}
STATE_LABEL = {"STANDBY": "STANDBY", "LISTENING": "LISTENING", "THINKING": "THINKING", "SPEAKING": "SPEAKING"}

# ---------------------------------------------------------------- hook Jarvis
_q = queue.Queue()
_orig_speak = jarvis.speak
_orig_listen = jarvis.listen


def _hooked_speak(text):
    _q.put(("speak_start", text))
    try:
        _orig_speak(text)
    finally:
        _q.put(("speak_end", None))


def _hooked_listen():
    text = _orig_listen()
    if text:
        _q.put(("you", text))
    return text


jarvis.speak = _hooked_speak
jarvis.listen = _hooked_listen


def _load_extensions():
    """Same chain as the other HUDs: phone -> apps -> desktop, plus the optional welcome routine."""
    for name in ("jarvis_phone", "jarvis_apps", "jarvis_desktop"):
        try:
            __import__(name)
            break
        except Exception as e:
            print(f"(extension {name} not loaded: {type(e).__name__}: {e})")
    try:
        __import__("jarvis_welcome")
    except ImportError:
        pass
    except Exception as e:
        print(f"(jarvis_welcome not loaded: {type(e).__name__}: {e})")


# ---------------------------------------------------------------- helpers
AL_LT = int(Qt.AlignmentFlag.AlignLeft.value | Qt.AlignmentFlag.AlignTop.value | Qt.TextFlag.TextWordWrap.value)
AL_C = int(Qt.AlignmentFlag.AlignCenter.value)
AL_L = int(Qt.AlignmentFlag.AlignLeft.value | Qt.AlignmentFlag.AlignVCenter.value)
AL_R = int(Qt.AlignmentFlag.AlignRight.value | Qt.AlignmentFlag.AlignVCenter.value)
PLUS = QPainter.CompositionMode.CompositionMode_Plus
OVER = QPainter.CompositionMode.CompositionMode_SourceOver


def qcol(rgb, a=255):
    return QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), max(0, min(255, int(a))))


def lerp(a, b, k):
    return a + (b - a) * k


def clamp01(x):
    return max(0.0, min(1.0, x))


def ease_out_back(x):
    x = clamp01(x)
    c1, c3 = 1.4, 2.4
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


# ---------------------------------------------------------------- the HUD
class Hud(QWidget):
    def __init__(self, size=None, avail=None):
        """size/avail are only used for off-screen previews; normally the HUD covers the primary screen."""
        super().__init__()
        self.headless = size is not None
        if not self.headless:
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                                | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                                | Qt.WindowType.WindowDoesNotAcceptFocus)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            screen = QGuiApplication.primaryScreen()
            geo, av = screen.geometry(), screen.availableGeometry()
            # one pixel short of full height so Windows does not treat it as a fullscreen app
            self.setGeometry(geo.x(), geo.y(), geo.width(), geo.height() - 1)
            avail = QRectF(av.x() - geo.x(), av.y() - geo.y(), av.width(), av.height() - 1)
        else:
            self.resize(size[0], size[1])
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._avail = avail

        # state
        self.state = "STANDBY"
        self.color = list(C_CYAN)
        self.vis = 0.0
        self.vis_target = 0.0
        self.shown_at = 0.0
        self.hide_at = None
        self.think_since = None
        self.key_was_down = False
        self.user_text = ""
        self.reply = ""
        self.type_t0 = 0.0
        self.level = 0.0
        self.clock = time.time()          # real time (clock display, typing speed)
        self._t_origin = self.clock
        self.anim = 0.0                   # seconds since the HUD started (all animations use this)
        self._warned = False
        self.stats = {"cpu": 0.0, "ram": 0.0, "bat": None, "plug": False}
        self._stats_at = 0.0
        self.intro = 1.0
        rnd = random.Random(7)
        self.particles = [(rnd.uniform(0, 6.28), rnd.uniform(0, 1), rnd.uniform(-0.25, 0.25),
                           rnd.uniform(1.2, 3.0), rnd.uniform(0, 6.28)) for _ in range(46)]
        self._vignette = None
        self._layout()

        if not self.headless:
            psutil.cpu_percent(None)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self._tick)
            self.timer.start(int(1000 / FPS))
            self._last = time.time()

    # ---------- layout
    def _layout(self):
        W, H = self.width(), self.height()
        self.s = max(0.4, H / 1080.0) * SCALE
        s = self.s
        a = self._avail if self._avail is not None else QRectF(0, 0, W, H - 48)
        self.R = 150 * s
        self.panel_w = min(680 * s, W * 0.42)
        self.panel_h = 300 * s
        gap = 64 * s
        cluster_w = 2 * self.R + gap + self.panel_w
        left = a.left() + (a.width() - cluster_w) / 2
        cy = a.bottom() - self.R - 92 * s
        self.orb_c = QPointF(left + self.R, cy)
        self.panel = QRectF(left + 2 * self.R + gap, cy - self.panel_h / 2, self.panel_w, self.panel_h)
        self._vignette = None

    def resizeEvent(self, e):
        self._layout()

    def _make_vignette(self):
        W, H = max(1, self.width()), max(1, self.height())
        pm = QPixmap(W, H)
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        if DIM_SCREEN > 0:
            g = QRadialGradient(QPointF(W / 2, H / 2), math.hypot(W, H) / 2)
            g.setColorAt(0.0, QColor(0, 0, 0, 0))
            g.setColorAt(0.55, QColor(0, 0, 0, 0))
            g.setColorAt(1.0, QColor(0, 6, 12, int(255 * DIM_SCREEN)))
            q.fillRect(0, 0, W, H, QBrush(g))
        # soft dark pool behind the orb + panel so they stay readable on bright wallpapers
        cx = self.orb_c.x() + (self.panel.right() - self.orb_c.x()) / 2
        cy = self.orb_c.y()
        q.translate(cx, cy)
        q.scale(1.0, 0.5)
        rad = (self.panel.right() - self.orb_c.x() + self.R) * 0.78
        g2 = QRadialGradient(QPointF(0, 0), rad)
        g2.setColorAt(0.0, QColor(0, 8, 16, 120))
        g2.setColorAt(0.7, QColor(0, 8, 16, 50))
        g2.setColorAt(1.0, QColor(0, 8, 16, 0))
        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(QBrush(g2))
        q.drawEllipse(QPointF(0, 0), rad, rad)
        q.end()
        self._vignette = pm

    # ---------- state machine
    def _key_down(self):
        if not getattr(jarvis, "PUSH_TO_TALK", False):
            return False
        try:
            fn = getattr(jarvis, "ptt_pressed", None)       # knows about the Copilot key
            if fn is not None:
                return bool(fn())
            kb = getattr(jarvis, "keyboard", None)
            return bool(kb and kb.is_pressed(jarvis.PTT_KEY))
        except Exception:
            return False

    def _show(self, now):
        if self.vis < 0.05:
            self.shown_at = now
        if not self.isVisible() and not self.headless:
            self.show()
        self.vis_target = 1.0
        self.hide_at = None

    def handle(self, kind, data, now):
        if kind == "you":
            wake = getattr(jarvis, "has_wake", lambda t: False)(data)
            if getattr(jarvis, "PUSH_TO_TALK", False) or wake or self.vis_target > 0:
                self._show(now)
                self.user_text = data
                self.state = "THINKING"
                self.think_since = now
        elif kind == "speak_start":
            self._show(now)
            self.state = "SPEAKING"
            self.reply = data
            self.type_t0 = now
            self.think_since = None
        elif kind == "speak_end":
            self.state = "STANDBY"
            self.hide_at = now + HIDE_DELAY
        elif kind == "exit":
            QApplication.quit()

    def advance(self, dt, now):
        """Move every animation forward by dt seconds."""
        self.clock = now
        self.anim = now - self._t_origin
        down = self._key_down()
        if down and not self.key_was_down:          # talk key pressed
            self._show(now)
            self.state = "LISTENING"
            self.user_text = ""
        elif self.key_was_down and not down and self.state == "LISTENING":   # released
            self.state = "THINKING"
            self.think_since = now
        self.key_was_down = down

        if self.state == "THINKING" and self.think_since and now - self.think_since > PTT_RELEASE_TIMEOUT:
            self.state = "STANDBY"                  # nothing came back (noise / not understood)
            self.hide_at = now
            self.think_since = None
        if self.hide_at is not None and now >= self.hide_at and not down and self.state == "STANDBY":
            self.vis_target = 0.0
            self.hide_at = None

        self.vis += (self.vis_target - self.vis) * min(1.0, dt * 7.0)
        if self.vis_target == 0.0 and self.vis < 0.02:
            self.vis = 0.0
            if self.isVisible() and not self.headless:
                self.hide()
        self.intro = 0.55 + 0.45 * ease_out_back((now - self.shown_at) / 0.9)

        tgt = STATE_COLOR[self.state]
        k = min(1.0, dt * 6.0)
        self.color = [lerp(self.color[i], tgt[i], k) for i in range(3)]

        t = now
        if self.state == "LISTENING":
            lvl = getattr(jarvis, "mic_level", None)
            target = 0.25 + 0.2 * math.sin(t * 5) if lvl is None else min(1.0, lvl * 10) + 0.07
        elif self.state == "SPEAKING":
            target = 0.35 + 0.35 * abs(math.sin(t * 7.3)) * (0.6 + 0.4 * math.sin(t * 2.1)) + random.uniform(0, 0.12)
        elif self.state == "THINKING":
            target = 0.13
        else:
            target = 0.07 + 0.03 * math.sin(t * 1.7)
        self.level += (target - self.level) * min(1.0, dt * 10.0)

        if now - self._stats_at > 1.0:
            self._stats_at = now
            try:
                b = psutil.sensors_battery()
                self.stats = {"cpu": psutil.cpu_percent(None), "ram": psutil.virtual_memory().percent,
                              "bat": None if b is None else b.percent, "plug": bool(b.power_plugged) if b else False}
            except Exception:
                pass

    def _tick(self):
        now = time.time()
        dt = min(0.2, now - self._last)
        self._last = now
        try:
            while True:
                kind, data = _q.get_nowait()
                self.handle(kind, data, now)
        except queue.Empty:
            pass
        self.advance(dt, now)
        if self.vis > 0.01:
            self.update()

    # ---------- painting helpers
    def font(self, px, family=FONT_BODY, weight=QFont.Weight.Normal, spacing=0.0):
        f = QFont(family)
        f.setPixelSize(max(6, int(px * self.s)))
        f.setWeight(weight)
        if spacing:
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing * self.s)
        return f

    def text(self, p, rect, flags, txt, font, rgb, alpha=255, shadow=True):
        p.setFont(font)
        if shadow:
            p.setPen(QColor(0, 0, 0, int(alpha * 0.65)))
            p.drawText(rect.translated(1.2 * self.s, 1.2 * self.s), flags, txt)
        p.setPen(qcol(rgb, alpha))
        p.drawText(rect, flags, txt)

    def stroke_glow(self, p, fn, rgb, width, alpha=255, glow=1.0):
        p.setBrush(Qt.BrushStyle.NoBrush)
        if glow > 0:
            p.setCompositionMode(PLUS)
            for mult, a in ((5.0, 12), (3.0, 24), (1.8, 50)):
                pen = QPen(qcol(rgb, a * glow * alpha / 255), width * mult)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                fn()
            p.setCompositionMode(OVER)
        pen = QPen(qcol(rgb, alpha), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        fn()

    def fade_dot(self, p, x, y, r, rgb, a=255):
        g = QRadialGradient(QPointF(x, y), r * 3)
        g.setColorAt(0.0, qcol((255, 255, 255), a))
        g.setColorAt(0.25, qcol(rgb, a * 0.8))
        g.setColorAt(1.0, qcol(rgb, 0))
        p.setCompositionMode(PLUS)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(x, y), r * 3, r * 3)
        p.setCompositionMode(OVER)

    # ---------- the picture
    def paintEvent(self, e):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            self.draw(p)
        except Exception as ex:
            if not self._warned:                     # say it once, not 30 times a second
                self._warned = True
                print(f"(HUD drawing problem: {type(ex).__name__}: {ex})")
        finally:
            p.end()

    def draw(self, p):
        if self.vis <= 0.005:
            return
        if self._vignette is None:
            self._make_vignette()
        t = self.anim
        p.setOpacity(clamp01(self.vis))
        p.drawPixmap(0, 0, self._vignette)
        if SHOW_CORNERS:
            self._draw_corners(p, t)
        self._draw_topbar(p, t)
        self._draw_link(p, t)
        self._draw_panel(p, t)
        self._draw_orb(p, t)
        p.setOpacity(1.0)

    def _draw_corners(self, p, t):
        s, W, H = self.s, self.width(), self.height()
        m, L = 34 * s, 74 * s
        col = self.color

        def brackets():
            for (x, y, dx, dy) in ((m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1), (W - m, H - m, -1, -1)):
                path = QPainterPath()
                path.moveTo(x, y + dy * L)
                path.lineTo(x, y)
                path.lineTo(x + dx * L, y)
                p.drawPath(path)
        self.stroke_glow(p, brackets, col, 2.2 * s, alpha=170, glow=0.8)

    def _draw_topbar(self, p, t):
        s, W = self.s, self.width()
        col = self.color
        if SHOW_CLOCK:
            f = self.font(64, FONT_HEAD, QFont.Weight.Light)
            hhmm = time.strftime("%I:%M", time.localtime(self.clock))
            if hhmm.startswith("0"):
                hhmm = hhmm[1:]
            fm = QFontMetrics(f)
            w = fm.horizontalAdvance(hhmm)
            self.text(p, QRectF(78 * s, 58 * s, w + 10, 76 * s), AL_L, hhmm, f, (230, 248, 255))
            self.text(p, QRectF(78 * s + w + 12 * s, 74 * s, 70 * s, 30 * s), AL_L,
                      time.strftime("%p", time.localtime(self.clock)), self.font(20, FONT_HEAD, QFont.Weight.DemiBold, 2), col)
            date = time.strftime("%A  |  %d %B %Y", time.localtime(self.clock)).upper()
            self.text(p, QRectF(80 * s, 136 * s, 520 * s, 24 * s), AL_L, date,
                      self.font(13, FONT_HEAD, QFont.Weight.Normal, 3), (150, 205, 225), 220)
        # centre logo with side lines
        cx, y = W / 2, 56 * s
        logo = "J . A . R . V . I . S"
        f = self.font(20, FONT_HEAD, QFont.Weight.DemiBold, 5)
        fm = QFontMetrics(f)
        lw = fm.horizontalAdvance(logo)
        self.text(p, QRectF(cx - lw / 2, y - 16 * s, lw + 10, 34 * s), AL_C, logo, f, (225, 247, 255))

        def lines():
            p.drawLine(QPointF(cx - lw / 2 - 26 * s, y), QPointF(cx - lw / 2 - 190 * s, y))
            p.drawLine(QPointF(cx + lw / 2 + 26 * s, y), QPointF(cx + lw / 2 + 190 * s, y))
        self.stroke_glow(p, lines, col, 1.4 * s, alpha=150, glow=0.6)
        pulse = 0.5 + 0.5 * math.sin(t * 3)
        self.fade_dot(p, cx - lw / 2 - 12 * s, y, 3.2 * s, C_GREEN, 140 + 100 * pulse)
        self.fade_dot(p, cx + lw / 2 + 12 * s, y, 3.2 * s, C_GREEN, 140 + 100 * pulse)

        if SHOW_STATS:
            rows = [("CPU", self.stats["cpu"]), ("RAM", self.stats["ram"])]
            if self.stats["bat"] is not None:
                rows.append(("BAT" if not self.stats["plug"] else "CHG", self.stats["bat"]))
            x_right = W - 84 * s
            bar_w, y0 = 210 * s, 76 * s
            self.text(p, QRectF(x_right - 330 * s, y0 - 22 * s, 330 * s, 18 * s), AL_R, "SYSTEM STATUS",
                      self.font(12, FONT_HEAD, QFont.Weight.Normal, 4), (150, 205, 225), 210)
            for i, (name, val) in enumerate(rows):
                yy = y0 + i * 30 * s
                rgb = C_AMBER if (name != "CHG" and ((name == "BAT" and val < 20) or (name != "BAT" and val > 85))) else col
                self.text(p, QRectF(x_right - 330 * s, yy, 50 * s, 20 * s), AL_L, name,
                          self.font(13, FONT_HEAD, QFont.Weight.DemiBold, 2), (200, 232, 245))
                bx = x_right - 270 * s
                track = QRectF(bx, yy + 7 * s, bar_w, 6 * s)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qcol((120, 190, 215), 45))
                p.drawRoundedRect(track, 3 * s, 3 * s)
                fill = QRectF(bx, yy + 7 * s, max(4 * s, bar_w * clamp01(val / 100.0)), 6 * s)
                g = QLinearGradient(fill.left(), 0, fill.right(), 0)
                g.setColorAt(0.0, qcol(rgb, 90))
                g.setColorAt(1.0, qcol(rgb, 255))
                p.setBrush(QBrush(g))
                p.drawRoundedRect(fill, 3 * s, 3 * s)
                p.setCompositionMode(PLUS)
                p.setBrush(qcol(rgb, 40))
                p.drawRoundedRect(fill.adjusted(-2 * s, -3 * s, 2 * s, 3 * s), 5 * s, 5 * s)
                p.setCompositionMode(OVER)
                self.text(p, QRectF(bx + bar_w + 10 * s, yy, 58 * s, 20 * s), AL_R, f"{val:.0f}%",
                          self.font(13, FONT_HEAD, QFont.Weight.Normal, 1), (225, 245, 255))

    def _draw_link(self, p, t):
        s = self.s
        c, R = self.orb_c, self.R * self.intro
        x1, x2, y = c.x() + R * 1.05, self.panel.left(), c.y()
        col = self.color

        def line():
            p.drawLine(QPointF(x1, y), QPointF(x2, y))
        self.stroke_glow(p, line, col, 1.3 * s, alpha=120, glow=0.5)
        active = self.state in ("THINKING", "SPEAKING", "LISTENING")
        speed = 0.9 if self.state != "THINKING" else 1.8
        n = 3 if active else 1
        for i in range(n):
            ph = (t * speed + i / n) % 1.0
            self.fade_dot(p, lerp(x1, x2, ph), y, 2.6 * s, col, 230 * (1 - abs(ph - 0.5) * 1.2))

    def _draw_panel(self, p, t):
        s, col = self.s, self.color
        r = self.panel
        pad = 28 * s
        # glass
        g = QLinearGradient(r.left(), r.top(), r.left(), r.bottom())
        g.setColorAt(0.0, QColor(8, 26, 38, 205))
        g.setColorAt(1.0, QColor(4, 14, 24, 225))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(r, 16 * s, 16 * s)
        # soft inner glow along the top edge
        hg = QLinearGradient(r.left(), r.top(), r.left(), r.top() + 70 * s)
        hg.setColorAt(0.0, qcol(col, 38))
        hg.setColorAt(1.0, qcol(col, 0))
        p.setBrush(QBrush(hg))
        p.drawRoundedRect(r, 16 * s, 16 * s)
        # borders: thin solid + marching dashes
        path = QPainterPath()
        path.addRoundedRect(r, 16 * s, 16 * s)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qcol(col, 70), 1.2 * s))
        p.drawPath(path)
        pen = QPen(qcol(col, 190), 1.8 * s)
        pen.setDashPattern([10, 26])
        pen.setDashOffset(-t * 7)
        p.setPen(pen)
        p.drawPath(path)

        # bright corner brackets
        def corners():
            L = 26 * s
            for (x, y, dx, dy) in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                                   (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
                q = QPainterPath()
                q.moveTo(x, y + dy * L)
                q.lineTo(x, y)
                q.lineTo(x + dx * L, y)
                p.drawPath(q)
        self.stroke_glow(p, corners, col, 2.6 * s, alpha=255, glow=1.0)

        # header
        x0, wtxt = r.left() + pad, r.width() - 2 * pad
        self.text(p, QRectF(x0, r.top() + 16 * s, wtxt * 0.7, 20 * s), AL_L, "NEURAL INTERFACE  //  ONLINE",
                  self.font(12, FONT_HEAD, QFont.Weight.DemiBold, 3), col, 230)
        lang = getattr(jarvis, "_lang", "en")
        badge = "EN" if lang != "ta" else "TA > EN"
        mic = (getattr(jarvis, "_last_mic", [None]) or [None])[0]
        m = re.search(r"\((.+)\)", str(mic or ""))
        mic_short = (m.group(1) if m else str(mic or "")).strip()[:22].upper()
        right = badge if not mic_short else f"{badge}   |   MIC  {mic_short}"
        self.text(p, QRectF(x0 + wtxt * 0.45, r.top() + 16 * s, wtxt * 0.55, 20 * s), AL_R, right,
                  self.font(11, FONT_HEAD, QFont.Weight.Normal, 2), (150, 205, 225), 220)

        def sep():
            p.drawLine(QPointF(x0, r.top() + 46 * s), QPointF(r.right() - pad, r.top() + 46 * s))
        self.stroke_glow(p, sep, col, 1.0 * s, alpha=90, glow=0.0)

        def sep_hot():
            xa = x0 + ((t * 120 * s) % (wtxt + 120 * s)) - 120 * s
            p.drawLine(QPointF(max(x0, xa), r.top() + 46 * s), QPointF(min(r.right() - pad, xa + 120 * s), r.top() + 46 * s))
        if self.state != "STANDBY":
            self.stroke_glow(p, sep_hot, col, 1.6 * s, alpha=230, glow=0.8)

        # you
        y = r.top() + 62 * s
        self.text(p, QRectF(x0, y, 120 * s, 16 * s), AL_L, "YOU  >", self.font(11, FONT_HEAD, QFont.Weight.DemiBold, 3),
                  (140, 190, 210), 230)
        you = self.user_text or ("..." if self.state == "LISTENING" else "")
        self.text(p, QRectF(x0, y + 20 * s, wtxt, 50 * s), AL_LT, self._fit(you, 18, wtxt, 2),
                  self.font(18, FONT_BODY, QFont.Weight.Normal), (205, 232, 245), 235)

        # equalizer strip
        n_bars, bw, gp = 34, 6 * s, 4 * s
        base_y = r.bottom() - 24 * s
        for i in range(n_bars):
            v = 0.5 + 0.5 * math.sin(t * 6.0 + i * 0.55) * math.sin(t * 2.3 + i * 0.21)
            h = (3 + 22 * clamp01(self.level * 1.3) * v) * s
            a = 90 + 130 * clamp01(self.level * 1.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcol(col, a))
            p.drawRoundedRect(QRectF(x0 + i * (bw + gp), base_y - h, bw, h), 1.5 * s, 1.5 * s)

        # jarvis
        y2 = r.top() + 142 * s
        self.text(p, QRectF(x0, y2, 160 * s, 16 * s), AL_L, "JARVIS  >", self.font(11, FONT_HEAD, QFont.Weight.DemiBold, 3), col, 255)
        n = int(max(0.0, self.clock - self.type_t0) * TYPE_CPS) if self.state == "SPEAKING" else len(self.reply)
        shown = self.reply[:n]
        typing = self.state == "SPEAKING" and n < len(self.reply)
        caret = "\u258c" if (self.state == "SPEAKING" and int(t * 2.5) % 2 == 0) or typing else ""
        body = self._fit(shown, 22, wtxt, 4) + caret
        self.text(p, QRectF(x0, y2 + 22 * s, wtxt, 100 * s), AL_LT, body,
                  self.font(22, FONT_BODY, QFont.Weight.Light), (240, 252, 255), 255)

    def _fit(self, txt, px, width, lines):
        """Keep the end of a long text so it fits the given number of lines."""
        if not txt:
            return ""
        fm = QFontMetrics(self.font(px))
        per_line = max(8, int(width / max(1.0, fm.averageCharWidth())))
        cap = int(per_line * lines * 0.92)
        if len(txt) <= cap:
            return txt
        cut = txt[-cap:]
        sp = cut.find(" ")
        return "\u2026" + (cut[sp + 1:] if 0 <= sp < 25 else cut)

    def _draw_orb(self, p, t):
        s = self.s
        cx, cy = self.orb_c.x(), self.orb_c.y()
        R = self.R * self.intro
        col, st, lvl = self.color, self.state, self.level
        center = QPointF(cx, cy)
        p.setPen(Qt.PenStyle.NoPen)

        # dark disc behind the orb: the neon stays readable even over a white window
        dg = QRadialGradient(center, R * 1.35)
        dg.setColorAt(0.0, QColor(2, 10, 18, 215))
        dg.setColorAt(0.72, QColor(2, 10, 18, 190))
        dg.setColorAt(1.0, QColor(2, 10, 18, 0))
        p.setBrush(QBrush(dg))
        p.drawEllipse(center, R * 1.35, R * 1.35)

        # halo
        g = QRadialGradient(center, R * 1.75)
        g.setColorAt(0.0, qcol(col, 40 + 30 * lvl))
        g.setColorAt(0.5, qcol(col, 20))
        g.setColorAt(1.0, qcol(col, 0))
        p.setCompositionMode(PLUS)
        p.setBrush(QBrush(g))
        p.drawEllipse(center, R * 1.75, R * 1.75)
        p.setCompositionMode(OVER)

        # floating particles
        for (a0, rf, sp, size, ph) in self.particles:
            a = a0 + t * sp
            rr = R * (1.08 + rf * 0.85)
            alpha = 150 * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 1.6 + ph)))
            self.fade_dot(p, cx + rr * math.cos(a), cy + rr * math.sin(a) * 0.92, size * s * 0.55, col, alpha)

        # outer ring + tick marks
        def outer():
            p.drawEllipse(center, R * 0.94, R * 0.94)
        self.stroke_glow(p, outer, col, 1.6 * s, alpha=190, glow=0.7)

        def ticks():
            path = QPainterPath()
            rot = t * 8
            for i in range(120):
                a = math.radians(rot + i * 3)
                long_, mid = i % 10 == 0, i % 5 == 0
                r1, r2 = R * 0.965, R * (1.045 if long_ else 1.0 if mid else 0.985)
                path.moveTo(cx + r1 * math.cos(a), cy + r1 * math.sin(a))
                path.lineTo(cx + r2 * math.cos(a), cy + r2 * math.sin(a))
            p.drawPath(path)
        self.stroke_glow(p, ticks, col, 1.4 * s, alpha=150, glow=0.0)

        # thick segmented ring (turns the other way)
        r2 = R * 0.82
        rect2 = QRectF(cx - r2, cy - r2, 2 * r2, 2 * r2)

        def segments():
            base = -t * 24
            for start, span in ((0, 70), (95, 40), (160, 92), (270, 56)):
                p.drawArc(rect2, int(((base + start) % 360) * 16), int(span * 16))
        self.stroke_glow(p, segments, col, 5.5 * s, alpha=235, glow=1.0)

        # dashed ring
        r3 = R * 0.68
        pen = QPen(qcol(col, 210), 2.0 * s)
        pen.setDashPattern([2.0, 4.0])
        pen.setDashOffset(t * 6)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(center, r3, r3)
        p.setPen(QPen(qcol(col, 110), 1.3 * s))
        p.drawEllipse(center, R * 0.60, R * 0.60)

        # thinking: comets orbiting
        if st == "THINKING":
            rc = R * 0.82
            rectc = QRectF(cx - rc, cy - rc, 2 * rc, 2 * rc)
            for j in range(3):
                head = -t * 250 + j * 120
                for m in range(9):
                    pen = QPen(qcol(C_AMBER, 255 * (1 - m / 9.0) ** 1.5), 6.5 * s)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    p.setPen(pen)
                    p.drawArc(rectc, int(((head + m * 5) % 360) * 16), int(-6 * 16))
        # speaking: ripples out of the core
        if st == "SPEAKING":
            p.setBrush(Qt.BrushStyle.NoBrush)
            for k in range(3):
                ph = (t * 0.9 + k / 3.0) % 1.0
                rr = R * (0.28 + 0.62 * ph)
                p.setPen(QPen(qcol(col, 120 * (1 - ph)), 2.0 * s))
                p.drawEllipse(center, rr, rr)

        # waveform ring (moves with your voice)
        r0 = R * 0.47
        amp = R * 0.11 * clamp01(lvl)

        def wave(phase, scale):
            path = QPainterPath()
            n = 150
            for i in range(n + 1):
                th = 2 * math.pi * i / n
                v = (math.sin(th * 5 + t * 3.1 + phase) + 0.7 * math.sin(th * 8 - t * 4.3 + phase)
                     + 0.5 * math.sin(th * 13 + t * 6.1)) / 2.2
                rr = r0 + amp * scale * v * (0.55 + 0.45 * math.sin(th * 3 + t * 2))
                pt = QPointF(cx + rr * math.cos(th), cy + rr * math.sin(th))
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            return path
        w2 = wave(2.0, 0.7)
        self.stroke_glow(p, lambda: p.drawPath(w2), col, 1.2 * s, alpha=120, glow=0.0)
        w1 = wave(0.0, 1.0)
        self.stroke_glow(p, lambda: p.drawPath(w1), col, 2.2 * s, alpha=255, glow=0.8)

        # glowing core
        cr = R * 0.20 * (1 + 0.05 * math.sin(t * 3) + 0.15 * lvl)
        g = QRadialGradient(center, cr * 1.7)
        g.setColorAt(0.0, QColor(235, 252, 255, 230))
        g.setColorAt(0.22, qcol(col, 200))
        g.setColorAt(0.6, qcol(col, 60))
        g.setColorAt(1.0, qcol(col, 0))
        p.setCompositionMode(PLUS)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(center, cr * 1.7, cr * 1.7)
        p.setCompositionMode(OVER)

        # state label
        self.text(p, QRectF(cx - R, cy + R * 1.18, 2 * R, 30 * s), AL_C, STATE_LABEL[st],
                  self.font(16, FONT_HEAD, QFont.Weight.DemiBold, 7), col, 255)


# ---------------------------------------------------------------- run
def main():
    _load_extensions()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    hud = Hud()  # noqa: F841  (kept alive by Qt)

    def backend():
        try:
            jarvis.main()
        finally:
            _q.put(("exit", None))

    threading.Thread(target=backend, daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
