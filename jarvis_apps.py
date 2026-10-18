"""
JARVIS apps/web extension: auto-detects EVERY installed app (no hardcoding),
plus WhatsApp Web / Gmail / Spotify control via a real Chrome browser.

Setup:  pip install selenium   (Google Chrome must be installed)

Run (this is the main entry point -- includes desktop + core too):
  python jarvis_apps.py

FIRST TIME: asking for WhatsApp/Gmail opens a Chrome window -- log in /
scan the QR code once. It's saved in .jarvis_chrome_profile for next time.
"""
import glob
import os
import time

import jarvis

try:
    import jarvis_desktop  # noqa: F401
except ImportError:
    pass

SHORTCUT_DIRS = [
    os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
    os.path.expandvars(r"%AppData%\Microsoft\Windows\Start Menu\Programs"),
]


def _all_shortcuts():
    found = {}
    for d in SHORTCUT_DIRS:
        for path in glob.glob(os.path.join(d, "**", "*.lnk"), recursive=True):
            name = os.path.splitext(os.path.basename(path))[0]
            found[name.lower()] = path
    return found


def list_installed_apps():
    names = sorted(_all_shortcuts().keys())
    return ", ".join(names[:60]) + (f" ... and {len(names)-60} more" if len(names) > 60 else "")


def open_installed_app(name):
    shortcuts = _all_shortcuts()
    key = name.lower().strip()
    if key in shortcuts:
        os.startfile(shortcuts[key])
        return f"Opened {name}"
    matches = [n for n in shortcuts if key in n]
    if matches:
        os.startfile(shortcuts[matches[0]])
        return f"Opened {matches[0]} (closest match to '{name}')"
    return f"No installed app matched '{name}'."


_driver = None
PROFILE_DIR = os.path.join(os.path.expanduser("~"), ".jarvis_chrome_profile")


def _get_driver():
    global _driver
    if _driver is not None:
        return _driver
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_experimental_option("detach", True)
    _driver = webdriver.Chrome(options=opts)
    return _driver


def whatsapp_send(contact, message):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    d = _get_driver()
    d.get("https://web.whatsapp.com")
    for _ in range(30):
        if d.find_elements(By.XPATH, "//div[@contenteditable='true'][@data-tab='3']"):
            break
        time.sleep(1)
    else:
        return "WhatsApp Web not logged in. Scan the QR code in the opened Chrome window, then try again."
    search = d.find_element(By.XPATH, "//div[@contenteditable='true'][@data-tab='3']")
    search.click()
    search.send_keys(contact)
    time.sleep(2)
    results = d.find_elements(By.XPATH, f"//span[@title='{contact}']")
    if not results:
        return f"Could not find contact '{contact}' in WhatsApp."
    results[0].click()
    time.sleep(1)
    box = d.find_element(By.XPATH, "//div[@contenteditable='true'][@data-tab='10']")
    box.click()
    box.send_keys(message)
    box.send_keys(Keys.ENTER)
    return f"Message sent to {contact}."


def gmail_check(max_emails=5):
    from selenium.webdriver.common.by import By
    d = _get_driver()
    d.get("https://mail.google.com/mail/u/0/#inbox")
    time.sleep(4)
    rows = d.find_elements(By.CSS_SELECTOR, "tr.zA")[:max_emails]
    if not rows:
        return "Could not read inbox. Log into Gmail in the opened Chrome window."
    out = []
    for row in rows:
        try:
            sender = row.find_element(By.CSS_SELECTOR, ".yX .yW span").text
            subject = row.find_element(By.CSS_SELECTOR, ".y6 span span").text
            out.append(f"{sender}: {subject}")
        except Exception:
            continue
    return "\n".join(out) or "No readable emails found."


def spotify_play(query):
    shortcuts = _all_shortcuts()
    if "spotify" in shortcuts:
        os.startfile(shortcuts["spotify"])
        time.sleep(3)
        return f"Opened Spotify app. Search for '{query}' and press play."
    import webbrowser
    import urllib.parse
    webbrowser.open("https://open.spotify.com/search/" + urllib.parse.quote(query))
    return f"Opened Spotify web search for '{query}'."


NEW_TOOLS = {
    "list_installed_apps": (list_installed_apps, "{}  -- List every installed app Jarvis can open."),
    "open_installed_app": (open_installed_app, '{"name": str}  -- Open ANY installed app by name (fuzzy match).'),
    "whatsapp_send": (whatsapp_send, '{"contact": str, "message": str}  -- Send a WhatsApp message via WhatsApp Web.'),
    "gmail_check": (gmail_check, "{}  -- Read the subject lines of recent Gmail inbox emails."),
    "spotify_play": (spotify_play, '{"query": str}  -- Open Spotify and search for a song/artist.'),
}

for name, (fn, desc) in NEW_TOOLS.items():
    jarvis.register_tool(name, fn, desc)

if __name__ == "__main__":
    jarvis.main()
