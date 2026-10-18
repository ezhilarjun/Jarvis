"""
Makes Windows start the SAME Jarvis HUD at login that you start by hand (jarvis_hud_pro.py).

Run:   py -3.12 fix_startup.py

What it does (it never deletes anything):
  1. Looks at everything that starts with Windows and mentions Jarvis:
     the Startup folder, Task Scheduler and the registry "Run" keys.
  2. Moves old Jarvis items out of the Startup folder into  C:\\jarvis\\old_startup_backup
     (put them back any time if you want them).
  3. Puts the new start_jarvis.vbs (which starts jarvis_hud_pro.py) into the Startup folder.
  4. Shows which Jarvis programs are running right now and offers to stop them.
A report is saved to  C:\\jarvis\\startup_report.txt
"""
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

JARVIS_DIR = Path(r"C:\jarvis")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SKIP = {"desktop.ini"}


def run_cmd(cmd):
    """Run a command, return its text output ('' if it fails)."""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=40, creationflags=NO_WINDOW)
        out = r.stdout.decode("utf-8", errors="replace") if r.stdout else ""
        if not out.strip() and r.stdout is not None:
            out = r.stdout.decode("cp1252", errors="replace")
        return out
    except Exception:
        return ""


def mentions_jarvis(path):
    """True if the file name, or what is inside it (also shortcuts), mentions Jarvis."""
    if "jarvis" in path.name.lower():
        return True
    try:
        data = path.read_bytes()[:200_000].lower()
    except Exception:
        return False
    return b"jarvis" in data or "jarvis".encode("utf-16-le") in data


def unique(dest):
    if not dest.exists():
        return dest
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return dest.with_name(f"{dest.stem}.{stamp}{dest.suffix}")


def find_scheduled_tasks(runner):
    out = runner(["schtasks", "/query", "/fo", "CSV", "/nh", "/v"])
    found = []
    for row in csv.reader(io.StringIO(out)):
        if row and "jarvis" in " ".join(row).lower():
            name = row[1] if len(row) > 1 and row[0].lower() == row[1].lower() else row[0]
            run = next((c for c in row if "jarvis" in c.lower() and c != name), "")
            found.append((name, run))
    return found


def find_run_keys(runner):
    found = []
    for hive in ("HKCU", "HKLM"):
        out = runner(["reg", "query", rf"{hive}\Software\Microsoft\Windows\CurrentVersion\Run"])
        for line in out.splitlines():
            if "jarvis" in line.lower():
                found.append(f"{hive}: {line.strip()}")
    return found


PS_LIST = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw|py)\\.exe$' } | "
           "ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessId, $_.Name, $_.CommandLine }")


def running_jarvis(runner, my_pid):
    out = runner(["powershell", "-NoProfile", "-Command", PS_LIST])
    procs = []
    for line in out.splitlines():
        parts = line.strip().split("|", 2)
        if len(parts) != 3 or "jarvis" not in parts[2].lower():
            continue
        pid = parts[0]
        if pid == str(my_pid):
            continue
        m = re.search(r"([\w\-]*jarvis[\w\-]*\.py)", parts[2], re.I)
        procs.append((pid, parts[1], m.group(1) if m else parts[2][:80]))
    return procs


def fix(jarvis_dir, startup_dir, runner=run_cmd, ask=input, my_pid=None, say=print):
    lines = []

    def out(text=""):
        lines.append(text)
        say(text)

    my_pid = my_pid or os.getpid()
    new_vbs = jarvis_dir / "start_jarvis.vbs"
    backup = jarvis_dir / "old_startup_backup"

    out("=== Jarvis start-up fixer ===")
    if not new_vbs.exists():
        out(f"\nCannot find {new_vbs}. Put the newest start_jarvis.vbs in {jarvis_dir} and run this again.")
        return lines, False
    if not (jarvis_dir / "jarvis_hud_pro.py").exists():
        out(f"\nWarning: {jarvis_dir}\\jarvis_hud_pro.py is missing. Put it there, otherwise login will start nothing.")

    out(f"\n1) Startup folder: {startup_dir}")
    startup_dir.mkdir(parents=True, exist_ok=True)
    items = [p for p in sorted(startup_dir.iterdir()) if p.is_file() and p.name.lower() not in SKIP]
    if not items:
        out("   (empty)")
    moved = []
    for p in items:
        if mentions_jarvis(p):
            backup.mkdir(parents=True, exist_ok=True)
            target = unique(backup / p.name)
            shutil.move(str(p), str(target))
            moved.append(p.name)
            out(f"   MOVED old Jarvis item: {p.name}  ->  {target}")
        else:
            out(f"   kept (not Jarvis): {p.name}")

    shutil.copy2(new_vbs, startup_dir / "start_jarvis.vbs")
    out("   INSTALLED: start_jarvis.vbs  (starts jarvis_hud_pro.py, 30 seconds after login)")

    out("\n2) Task Scheduler tasks that mention Jarvis:")
    tasks = find_scheduled_tasks(runner)
    if tasks:
        for name, run in tasks:
            out(f"   {name}   ->   {run}")
        out("   These can start a second Jarvis. To remove one, open Command Prompt as administrator and run:")
        for name, _ in tasks:
            out(f'      schtasks /delete /tn "{name.lstrip(chr(92))}" /f')
    else:
        out("   none")

    out("\n3) Registry start-up entries that mention Jarvis:")
    keys = find_run_keys(runner)
    if keys:
        for k in keys:
            out(f"   {k}")
        out("   Remove these in Task Manager > Startup apps (disable) if they start another HUD.")
    else:
        out("   none")

    out("\n4) Jarvis programs running right now:")
    procs = running_jarvis(runner, my_pid)
    if procs:
        for pid, name, script in procs:
            out(f"   PID {pid:>6}  {name:<12} {script}")
        wrong = [p for p in procs if "hud_pro" not in p[2].lower() and p[1].lower() != "py.exe"]
        if wrong:
            out("   -> something other than jarvis_hud_pro.py is running: that is the HUD you did not want.")
        if ask("\n   Stop all of them now, so you can test cleanly? (y/n): ").strip().lower().startswith("y"):
            for pid, _, _ in procs:
                runner(["taskkill", "/PID", pid, "/F", "/T"])
            out("   stopped.")
    else:
        out("   none")

    out("\nDONE. Restart the laptop (or sign out and in). Only start_jarvis.vbs will start Jarvis, with HUD Pro.")
    if moved:
        out(f"Old items are safe in {backup}. Do not put them back unless you want that HUD again.")
    out("If the wrong HUD still appears, send me the file startup_report.txt.")
    return lines, True


def main():
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    lines, ok = fix(JARVIS_DIR, startup)
    try:
        (JARVIS_DIR / "startup_report.txt").write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        print(f"(could not save the report: {e})")
    input("\nPress Enter to close...")


if __name__ == "__main__":
    if sys.platform != "win32":
        print("This tool is for Windows.")
    else:
        main()
