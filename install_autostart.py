"""
One-step auto-start installer for Jarvis (Windows).

  py -3.12 install_autostart.py            install  (Jarvis starts ~20s after you log in)
  py -3.12 install_autostart.py remove     uninstall
  py -3.12 install_autostart.py status     show what is installed

It writes a small script into your Windows Startup folder that uses the EXACT
Python you run this with, so it doesn't depend on PATH at login.
Logs go to jarvis_log.txt in this folder.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STARTUP = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
TARGET = os.path.join(STARTUP, "start_jarvis.vbs")
DELAY_MS = 20000


def _vbs_string(s):
    return '"' + s.replace('"', '""') + '"'


def install():
    if not os.environ.get("APPDATA"):
        sys.exit("This installer is for Windows (APPDATA not found).")
    os.makedirs(STARTUP, exist_ok=True)
    py = sys.executable
    if py.lower().endswith("pythonw.exe"):
        py = py[:-len("pythonw.exe")] + "python.exe"
    cmd = f'cmd /c ""{py}" jarvis_hud.py > jarvis_log.txt 2>&1"'
    vbs = (
        "' Auto-start for Jarvis. Remove with: install_autostart.py remove\r\n"
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f"WScript.Sleep {DELAY_MS}\r\n"
        f"sh.CurrentDirectory = {_vbs_string(HERE)}\r\n"
        f"sh.Run {_vbs_string(cmd)}, 0, False\r\n"
    )
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(vbs)
    print("Installed:", TARGET)
    print("Python used:", py)
    print("Folder:", HERE)
    print("Jarvis will start about 20 seconds after you sign in to Windows.")
    print("Errors (if any) are written to:", os.path.join(HERE, "jarvis_log.txt"))


def remove():
    if os.path.exists(TARGET):
        os.remove(TARGET)
        print("Removed:", TARGET)
    else:
        print("Nothing to remove.")


def status():
    print("Startup folder:", STARTUP)
    print("Installed:", "YES" if os.path.exists(TARGET) else "NO")
    if os.path.exists(TARGET):
        print(open(TARGET, encoding="utf-8").read())
    others = [f for f in (os.listdir(STARTUP) if os.path.isdir(STARTUP) else []) if "jarvis" in f.lower()]
    print("Jarvis-related files in Startup:", others or "none")


if __name__ == "__main__":
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else "install"
    {"install": install, "remove": remove, "status": status}.get(arg, install)()
