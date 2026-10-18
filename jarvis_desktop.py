"""
JARVIS full desktop control (FREE / LOCAL version, works with jarvis.py + Ollama).
Keep jarvis.py in the same folder.
  pip install pyautogui pyperclip pillow pygetwindow
Run:  python jarvis_desktop.py      (NOT jarvis.py)

Safety:
- Risky actions (shell, write file, shutdown, etc.) need a spoken "yes".
- Emergency stop: move mouse to any screen corner (pyautogui failsafe).
"""
import base64
import io
import os
import platform
import subprocess

import pyautogui
import pyperclip
import requests

import jarvis

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15
OS = platform.system()

jarvis.SYSTEM += (
    " You control the user's whole computer through tools: mouse, keyboard, "
    "windows, files, shell, power, clipboard and screen vision. "
    "For multi-step tasks, call one tool, wait for its result, then decide the next step. "
    "Never claim an action succeeded unless the tool result says so."
)

BLOCKED = ("rm -rf /", "format c:", "del /s /q c:\\", "mkfs", ":(){", "dd if=")


def confirm(question):
    jarvis.speak(question + " Say yes to confirm.")
    ans = jarvis.listen().lower()
    return any(w in ans for w in ("yes", "yeah", "confirm", "proceed", "do it", "sure"))


def look_at_screen(question="Describe what is on the screen."):
    img = pyautogui.screenshot()
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    try:
        r = requests.post(
            jarvis.OLLAMA_URL,
            json={
                "model": "llava",
                "messages": [{"role": "user", "content": question, "images": [b64]}],
                "stream": False,
            },
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]
    except Exception as e:
        return f"Vision model not available ({e}). Run: ollama pull llava"


def take_screenshot():
    path = os.path.join(os.path.expanduser("~"), "Pictures", "jarvis_shot.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pyautogui.screenshot(path)
    return f"Saved screenshot at {path}"


def type_text(text):
    pyperclip.copy(text)
    pyautogui.hotkey("command" if OS == "Darwin" else "ctrl", "v")
    return "Typed"


def press_keys(keys):
    pyautogui.hotkey(*[k.strip() for k in keys.lower().split("+")])
    return f"Pressed {keys}"


def click_at(x, y, double=False):
    pyautogui.click(int(x), int(y), clicks=2 if double else 1)
    return f"Clicked {x},{y}"


def scroll(amount):
    pyautogui.scroll(int(amount))
    return "Scrolled"


def screen_size():
    return str(pyautogui.size())


def media_key(action):
    ok = ("volumeup", "volumedown", "volumemute", "playpause", "nexttrack", "prevtrack")
    if action not in ok:
        return f"Use one of {ok}"
    for _ in range(5 if action in ("volumeup", "volumedown") else 1):
        pyautogui.press(action)
    return f"Done {action}"


def open_anything(target):
    if OS == "Windows":
        os.startfile(target) if os.path.exists(target) else subprocess.Popen(f'start "" "{target}"', shell=True)
    elif OS == "Darwin":
        subprocess.Popen(["open", "-a", target] if not os.path.exists(target) and "://" not in target else ["open", target])
    else:
        subprocess.Popen(["xdg-open", target] if os.path.exists(target) or "://" in target else [target])
    return f"Opened {target}"


def list_windows():
    import pygetwindow as gw
    return str([t for t in gw.getAllTitles() if t.strip()])


def focus_window(title):
    import pygetwindow as gw
    w = gw.getWindowsWithTitle(title)
    if not w:
        return "No such window"
    w[0].activate()
    return f"Focused {w[0].title}"


def close_window(title):
    import pygetwindow as gw
    w = gw.getWindowsWithTitle(title)
    if not w:
        return "No such window"
    w[0].close()
    return "Closed"


def run_command(cmd):
    if any(b in cmd.lower() for b in BLOCKED):
        return "Blocked: too dangerous."
    if not confirm(f"Shall I run: {cmd}?"):
        return "User declined."
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    return (p.stdout + p.stderr)[-1500:] or "Done (no output)"


def list_dir(path="~"):
    p = os.path.expanduser(path)
    return "\n".join(sorted(os.listdir(p))[:80])


def find_files(filename, root="~"):
    root = os.path.expanduser(root)
    hits = []
    for d, _, files in os.walk(root):
        for f in files:
            if filename.lower() in f.lower():
                hits.append(os.path.join(d, f))
                if len(hits) >= 15:
                    return "\n".join(hits)
    return "\n".join(hits) or "Nothing found"


def read_file(path):
    with open(os.path.expanduser(path), "r", errors="ignore") as f:
        return f.read(3000)


def write_file(path, content):
    path = os.path.expanduser(path)
    if not confirm(f"Write to {path}?"):
        return "User declined."
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return "File written"


def get_clipboard():
    return pyperclip.paste()[:2000]


def set_clipboard(text):
    pyperclip.copy(text)
    return "Copied"


def power(action):
    cmds = {
        "Windows": {"lock": "rundll32.exe user32.dll,LockWorkStation", "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
                    "shutdown": "shutdown /s /t 10", "restart": "shutdown /r /t 10", "cancel": "shutdown /a"},
        "Linux": {"lock": "loginctl lock-session", "sleep": "systemctl suspend",
                  "shutdown": "shutdown -h +0", "restart": "reboot", "cancel": "shutdown -c"},
        "Darwin": {"lock": "pmset displaysleepnow", "sleep": "pmset sleepnow",
                   "shutdown": "osascript -e 'tell app \"System Events\" to shut down'",
                   "restart": "osascript -e 'tell app \"System Events\" to restart'", "cancel": "true"},
    }[OS]
    if action not in cmds:
        return f"Use one of {list(cmds)}"
    if action in ("shutdown", "restart", "sleep") and not confirm(f"Really {action} the system?"):
        return "User declined."
    subprocess.Popen(cmds[action], shell=True)
    return f"{action} executed"


NEW_TOOLS = {
    "look_at_screen": (look_at_screen, '{"question": str}  -- Take a screenshot and answer a question about it.'),
    "take_screenshot": (take_screenshot, "{}  -- Save a screenshot to Pictures."),
    "type_text": (type_text, '{"text": str}  -- Type text into the focused window.'),
    "press_keys": (press_keys, '{"keys": str}  -- e.g. "ctrl+c", "alt+tab", "win", "enter".'),
    "click_at": (click_at, '{"x": num, "y": num}  -- Click at screen pixel coords.'),
    "scroll": (scroll, '{"amount": num}  -- positive=up, negative=down.'),
    "screen_size": (screen_size, "{}  -- Get screen resolution."),
    "media_key": (media_key, '{"action": str}  -- volumeup, volumedown, volumemute, playpause, nexttrack, prevtrack.'),
    "open_anything": (open_anything, '{"target": str}  -- Open any app, file, folder or URL.'),
    "list_windows": (list_windows, "{}  -- List open window titles."),
    "focus_window": (focus_window, '{"title": str}  -- Bring a window to front by title text.'),
    "close_window": (close_window, '{"title": str}  -- Close a window by title text.'),
    "run_command": (run_command, '{"cmd": str}  -- Run a shell command (asks user to confirm).'),
    "list_dir": (list_dir, '{"path": str}  -- List files in a folder.'),
    "find_files": (find_files, '{"filename": str, "root": str}  -- Find files by name under a root folder.'),
    "read_file": (read_file, '{"path": str}  -- Read a text file.'),
    "write_file": (write_file, '{"path": str, "content": str}  -- Write a text file (asks to confirm).'),
    "get_clipboard": (get_clipboard, "{}  -- Read the clipboard."),
    "set_clipboard": (set_clipboard, '{"text": str}  -- Set the clipboard.'),
    "power": (power, '{"action": str}  -- lock, sleep, shutdown, restart, cancel.'),
}

for name, (fn, desc) in NEW_TOOLS.items():
    jarvis.register_tool(name, fn, desc)

if __name__ == "__main__":
    jarvis.main()
