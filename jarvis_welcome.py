"""
"Jarvis, wake up" routine. Imported automatically by jarvis_hud.py.

Say "Jarvis, wake up" -> Jarvis greets you and opens the apps/sites listed below.
Edit the three settings to match what YOU want it to open.
"""
import os
import shutil
import subprocess
import threading
import webbrowser

import jarvis

WELCOME_PHRASE = "Welcome back, sir. All systems are online."

# Installed apps to open (matched against your Start Menu shortcuts).
# Examples: "cursor", "spotify", "chrome", "visual studio code"
OPEN_ON_WAKE = ["cursor"]

# Websites to open in your default browser, e.g. ["https://claude.ai/new"]
URLS_ON_WAKE = []


def _open_app(name):
    try:
        import jarvis_apps
        if jarvis_apps.open_installed_app(name).startswith("Opened"):
            return True
    except ImportError:
        pass
    exe = shutil.which(name)
    if exe:
        subprocess.Popen([exe])
        return True
    local = os.environ.get("LOCALAPPDATA", "")
    for p in (rf"{local}\Programs\cursor\Cursor.exe", rf"{local}\Programs\Cursor\Cursor.exe",
              rf"{local}\Programs\{name}\{name}.exe"):
        if os.path.exists(p):
            os.startfile(p)
            return True
    print(f"Wake-up: could not find app '{name}' (not installed? remove it from OPEN_ON_WAKE).")
    return False


def _open_everything():
    for name in OPEN_ON_WAKE:
        _open_app(name)
    for url in URLS_ON_WAKE:
        webbrowser.open(url)


def wake_up_routine():
    threading.Thread(target=_open_everything, daemon=True).start()
    jarvis.speak(WELCOME_PHRASE)
    return None  # already spoke


jarvis.FAST_COMMANDS.append((("wake up", "wake up now", "wakeup", "good morning"), wake_up_routine))
