"""
Shows what your keyboard sends when you press a key - use it to check your Copilot key.

Run:   py -3.12 test_copilot_key.py
Then press the Copilot key a few times: once as a quick tap, once held for a second or two.
Press Ctrl+C in the terminal to stop.

A Copilot key normally prints:
    down  left windows   ...
    down  left shift     ...
    down  f23            ...
    up    f23            ...   <-- held for 1.20 s
It also tells you whether the key can be HELD (long press) or only sends a quick TAP.
Jarvis handles both: hold to talk, or tap once to start and tap again to stop.

Note: this test does NOT block the key, so Windows may open Copilot while you test. Close it.
"""
import time

try:
    import keyboard
except ImportError:
    raise SystemExit("Install it first:  py -3.12 -m pip install keyboard")

TAP_SECONDS = 0.25
pressed_at = {}


def show(e):
    name = e.name or f"scan {e.scan_code}"
    line = f"{e.event_type:<5} {name:<16} scan_code={e.scan_code}"
    if (e.name or "").lower() == "f23" or e.scan_code == 110:
        if e.event_type == "down":
            pressed_at.setdefault(e.scan_code, time.time())   # ignore key-repeat events
        else:
            t0 = pressed_at.pop(e.scan_code, None)
            if t0:
                held = time.time() - t0
                kind = "a quick TAP" if held < TAP_SECONDS else "a HOLD"
                line += f"   <-- held for {held:.2f} s  ({kind})"
    print(line)


print("Press the Copilot key now (Ctrl+C to stop)...\n")
keyboard.hook(show)
try:
    keyboard.wait()
except KeyboardInterrupt:
    print("\nDone.")
