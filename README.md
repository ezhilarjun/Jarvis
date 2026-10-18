# JARVIS - a voice-controlled desktop assistant (Iron Man style)

Talk to your laptop. Jarvis listens through the microphone, understands **English and Tamil/Tanglish**, thinks with a **free AI model that runs on your own PC** (no API key, no cost), and then speaks back and **does things**: opens apps, searches the web, controls the mouse and keyboard, reads files, sends WhatsApp messages, controls an Android phone over ADB, and announces when a headset, Wi-Fi network or charger connects or disconnects.

Platform: **Windows 10/11**. Language: **Python 3.12**.

---

## Contents

1. [Features](#features)
2. [How it works](#how-it-works)
3. [Project files](#project-files)
4. [Requirements](#requirements)
5. [Installation](#installation)
6. [Running Jarvis](#running-jarvis)
7. [Using Jarvis](#using-jarvis)
8. [Tools Jarvis can use](#tools-jarvis-can-use)
9. [Configuration reference](#configuration-reference)
10. [Feature details](#feature-details)
11. [Phone control (ADB)](#phone-control-adb)
12. [Start automatically when Windows starts](#start-automatically-when-windows-starts)
13. [Extending Jarvis](#extending-jarvis)
14. [Safety and privacy](#safety-and-privacy)
15. [Troubleshooting](#troubleshooting)
16. [Status: what is tested and what is not](#status-what-is-tested-and-what-is-not)
17. [Ideas for later](#ideas-for-later)
18. [Built with](#built-with)

---

## Features

| Area | What Jarvis does |
|---|---|
| Voice in | Speech to text with Whisper (`faster-whisper`), on the GPU when possible. Understands English and Tamil/Tanglish. |
| Brain | A local AI model through Ollama (default `llama3.2:3b`). Free, offline, private. |
| Voice out | Natural voice with `edge-tts` (British voice for English, Indian-English voice for Tanglish). Falls back to the built-in Windows voice when there is no internet. |
| Noisy rooms | Push-to-talk on the laptop's **Copilot key** (hold it, or tap once to start and tap again to stop), background noise reduction, adaptive mic threshold, filter for Whisper's "thank you" hallucinations. |
| Desktop control | Mouse, keyboard, hotkeys, windows, clipboard, screenshots, volume/media keys, files, shell commands, lock/sleep/restart. |
| Apps | Opens **any installed app** by name (reads the Start Menu). |
| Web | Google search, YouTube search, WhatsApp Web messages, Gmail inbox subjects, Spotify search. |
| Screen vision | "What is on my screen?" using the `llava` vision model (optional). |
| Phone | Wake/unlock, open apps, back/home, tap/swipe, type, screenshot on an Android phone through ADB (cable or Wi-Fi). |
| Devices | Speaks when headsets, Bluetooth devices, USB drives, cameras, Wi-Fi networks or the charger connect/disconnect. Switches to a newly connected headset's microphone by itself. |
| HUD | Two designs. **HUD Pro**: a glowing see-through overlay with a rotating-ring orb that moves with your voice, a glass panel that types out the conversation, clock and CPU/RAM/battery meters. Or the classic **Iron Man** slide-in. |
| Phone to PC bridge | Optional small web server so an Android app (Tasker) can send commands to Jarvis. |
| Safety | Spoken confirmation ("say yes") for shell commands, file writes and shutdown/restart/sleep. Dangerous commands are blocked. |

---

## How it works

```
 Microphone (Copilot key, or wake word "Jarvis")
        |
        v
 noise reduction  ->  Whisper speech-to-text
                          |  detects English or Tamil/Tanglish
                          |  (Tamil is translated to English so everything downstream works)
                          v
                  instant commands (FAST_COMMANDS)? --yes--> run routine
                          | no
                          v
        Ollama AI model  <---- tool results ----+
                          |                      |
              plain answer?  or  tool call (JSON) |
                          |            \_________/
                          v        (desktop / apps / phone tools)
                 edge-tts voice  (offline Windows voice as fallback)
                          |
                          v
                      Speaker        HUD shows what was heard and said

 Background threads:  device watcher (headset / Bluetooth / USB / Wi-Fi / charger)
                      HUD animation
```

The AI answers either in plain words or with a JSON tool call such as `{"tool": "open_app", "args": {"name": "chrome"}}`. Jarvis runs the tool, gives the real result back to the AI, and the AI says the final answer.

---

## Project files

Put every file in one folder, for example `C:\jarvis`.

| File | What it is | Run it? |
|---|---|---|
| `jarvis.py` | **Core.** Microphone, Whisper, AI brain, voice, wake word, tool system, mic switching. Every other file builds on it. | For testing only |
| `jarvis_desktop.py` | Adds desktop-control tools (mouse, keyboard, files, shell, power, screenshot, vision). | Or run the HUD |
| `jarvis_apps.py` | Adds "open any installed app", WhatsApp, Gmail, Spotify. Loads `jarvis_desktop.py` too. | Or run the HUD |
| `jarvis_phone.py` | Adds Android phone control through ADB. Loads `jarvis_apps.py` and `jarvis_desktop.py` too. | Or run the HUD |
| `jarvis_hud_pro.py` | **Recommended entry point.** Starts Jarvis plus every extension above and shows the glowing HUD Pro overlay. Needs `PySide6`. | **Yes** |
| `jarvis_hud.py` | Alternative entry point with the classic Iron Man slide-in HUD (needs `ironman.png`). | Optional |
| `jarvis_devices.py` | Device watcher: announces connect/disconnect events and tells `jarvis.py` to re-scan audio. Started automatically by `jarvis.py`. | No |
| `jarvis_mobile.py` | Optional web server so a phone app (Tasker) can send text commands to Jarvis. | Optional |
| `ironman.png` | Picture used by the HUD. Replace it with any PNG (transparent or plain black background). | - |
| `start_jarvis.vbs` | Starts Jarvis silently at Windows login (HUD Pro, 30 s after login). Writes a line to `startup_check.txt` each time it runs. | Copy to Startup folder |
| `run_jarvis.bat` | Starts Jarvis with a visible window so you can read any error. | Double-click to test |
| `test_copilot_key.py` | Shows what the Copilot key sends and whether it can be held. | Optional |
| `fix_startup.py` | Fixes "a different HUD (or two Jarvis) starts at login": moves old Jarvis start-up items to a backup folder, installs the new `start_jarvis.vbs`, reports what else starts Jarvis. | Run once if needed |
| `test_mic.py` | Shows live microphone volume numbers, for debugging the mic. | Optional |
| `SETUP.txt` | Short step-by-step setup. | - |
| `jarvis_welcome.py` | *Optional.* If present, the HUD loads it. It adds a "Jarvis, wake up" / "good morning" routine through `FAST_COMMANDS`. | No |

How the extensions chain together: `jarvis_hud.py` loads `jarvis_phone.py`, which loads `jarvis_apps.py`, which loads `jarvis_desktop.py`, which loads `jarvis.py`. If a file is missing, the HUD falls back to the next one in the chain.

**Important:** keep all files from the same version. Mixing old and new files gives errors like `module 'jarvis' has no attribute ...` (see [Troubleshooting](#troubleshooting)).

---

## Requirements

- Windows 10 or 11
- Python **3.12** (installed with the `py` launcher). Python 3.14 is too new: `pygame` cannot be built for it yet.
- [Ollama](https://ollama.com) with a model (about 2 GB for `llama3.2:3b`)
- A microphone (a headset mic is best in a noisy room)
- Internet: only for the nicer `edge-tts` voice, web search, WhatsApp/Gmail. The AI and speech recognition work offline.
- Optional: NVIDIA GPU (much faster speech recognition and AI), Google Chrome (WhatsApp/Gmail), Android phone + USB cable (phone control)

The developer's laptop: 16 GB RAM, 8-core CPU, NVIDIA GPU, Windows 11. Ollama shows `100% GPU` for `llama3.2:3b` there.

---

## Installation

### 1. Python 3.12

Install Python 3.12 from python.org (or run `py install 3.12` if you use the Python install manager). Check:

```
py -3.12 --version
```

From now on always use `py -3.12`, not `python` (on many PCs `python` opens the Microsoft Store).

### 2. Ollama and the AI model

1. Install Ollama from <https://ollama.com>. It starts automatically in the system tray.
2. Download the model (one time):

```
ollama pull llama3.2:3b
```

Optional models:

```
ollama pull llava          # lets Jarvis look at your screen
ollama pull qwen2.5:7b     # bigger and better at Tamil/Tanglish replies, but slower
```

### 3. Put the files in a folder

Copy all the Jarvis files into `C:\jarvis`. Delete any older copies first.

### 4. Install the Python libraries (one command)

Open a terminal in `C:\jarvis` (type `cmd` in the folder's address bar) and run:

```
py -3.12 -m pip install faster-whisper sounddevice numpy edge-tts pygame psutil requests pyautogui pyperclip pillow pygetwindow selenium keyboard noisereduce
```

| Library | Used for |
|---|---|
| `faster-whisper` | Speech to text |
| `sounddevice`, `numpy` | Recording from the microphone |
| `noisereduce` | Removing background murmur |
| `keyboard` | The push-to-talk key |
| `edge-tts`, `pygame` | Speaking and playing the voice |
| `requests` | Talking to Ollama |
| `psutil` | CPU/RAM/battery/charger information |
| `pyautogui`, `pyperclip`, `pygetwindow` | Mouse, keyboard, clipboard, windows |
| `pillow` | Screenshots and the HUD picture |
| `selenium` | WhatsApp Web and Gmail automation |

Extra, only if you use them:

```
py -3.12 -m pip install PySide6                                 # jarvis_hud_pro.py (the glowing HUD, about 200 MB)
py -3.12 -m pip install flask                                   # jarvis_mobile.py
py -3.12 -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12    # GPU speech recognition (about 550 MB)
```

If `keyboard` or `noisereduce` is missing, Jarvis still runs: it switches to "always listening with the wake word" mode and skips noise reduction.

---

## Running Jarvis

```
cd C:\jarvis
py -3.12 jarvis_hud_pro.py
```

What you will see in the terminal:

1. `Loading speech model...` (the first run downloads the Whisper model, about 1.5 GB for `medium`).
2. `Speech model 'medium' running on GPU.` (or a message that it fell back to the CPU).
3. `JARVIS: Systems online. At your service, sir. Hold the Copilot key while you speak, or tap it to start and stop.`

To stop Jarvis press `Ctrl + C` in the terminal, or say **"goodbye"** or **"power down"**.

Other ways to start: `py -3.12 jarvis_hud.py` (classic Iron Man HUD), or without any HUD `py -3.12 jarvis_apps.py`, `py -3.12 jarvis_desktop.py`, `py -3.12 jarvis.py`. To see errors, double-click `run_jarvis.bat`.

---

## Using Jarvis

### Two ways to talk

**Push-to-talk (default) - the Copilot key.** The key that opens Copilot on new Windows 11 laptops is now Jarvis's talk key, so Ctrl+C, Ctrl+V and every other shortcut work normally and never trigger Jarvis.
- **Hold** the Copilot key, speak, let go; or
- **tap** it once to start, speak, **tap again** to stop (useful if your keyboard only sends a quick tap).
Everything else the microphone hears is ignored, so classmates talking nearby do not matter. You do not need to say "Jarvis" in this mode (you can, it is stripped). Jarvis swallows the key press, so Windows does not open Copilot. If your laptop has no Copilot key, or it does not work, set `PTT_KEY = "f8"` (or `"caps lock"`, `"right ctrl"` ...) in `jarvis.py`: other keys are hold-to-talk.

Not sure what your Copilot key sends? Run `py -3.12 test_copilot_key.py` and press it: it should print `left windows`, `left shift` and `f23`, and tells you whether it can be held or only taps.

**Wake word mode.** Used automatically if the `keyboard` library is missing, or when you set `PUSH_TO_TALK = False`. At start Jarvis listens to the room for 2 seconds (stay quiet) to set the mic sensitivity itself. Then say **"Jarvis, ..."**. For the next 30 seconds you can keep talking without repeating the wake word.

### Languages

- Speak **English** and Jarvis answers in English with the British voice.
- Speak **Tamil or Tanglish** and Jarvis answers in **Tanglish** (Tamil written in English letters) with an Indian-English voice.
- Jarvis chooses by itself for each sentence. The terminal shows `YOU (Tamil -> English): ...` when it understood Tamil.

### Example commands

| Say | What happens |
|---|---|
| "What time is it?" / "Ippo time enna?" | Tells the time |
| "Open notepad" / "Notepad open pannu" | Opens the app |
| "Open Photoshop" | Opens any installed app (Start Menu search) |
| "Search for Python tutorials" | Google search in the browser |
| "Play Anirudh songs on YouTube" | YouTube search results |
| "How is my system?" | CPU, RAM, battery |
| "What is on my screen?" | Screenshot described by the vision model (needs `llava`) |
| "Volume up" / "Pause the music" | Media keys |
| "Find files named budget" / "List files in downloads" | File tools |
| "Lock the computer" | Locks Windows |
| "Restart the laptop" | Asks "Say yes to confirm", then restarts |
| "Send WhatsApp message to Amma saying I will be late" | Sends it through WhatsApp Web |
| "Check my Gmail" | Reads the newest subject lines |
| "Wake my phone" / "Open WhatsApp on my phone" | Phone control through ADB |
| "Goodbye" / "Power down" | Stops Jarvis |

Note: the word **"shutdown"** also stops Jarvis itself (it is caught before the AI sees it). To turn the laptop off use "turn off the computer" or "power off".

---

## Tools Jarvis can use

The AI picks tools by name. Tools marked * ask for a spoken "yes" first.

**Core (`jarvis.py`)**

| Tool | Does |
|---|---|
| `get_time` | Current date and time |
| `open_app` | Opens notepad, calculator, chrome or vscode (allow-list `APPS`) |
| `web_search` | Google search |
| `play_youtube` | YouTube search |
| `system_status` | CPU, RAM, battery |

**Desktop (`jarvis_desktop.py`)**

| Tool | Does |
|---|---|
| `look_at_screen`, `take_screenshot` | Describe or save a screenshot |
| `type_text`, `press_keys`, `click_at`, `scroll`, `screen_size` | Keyboard and mouse |
| `media_key` | Volume up/down/mute, play/pause, next/previous |
| `open_anything` | Open an app, file, folder or URL |
| `list_windows`, `focus_window`, `close_window` | Window control |
| `run_command` * | Run a shell command |
| `list_dir`, `find_files`, `read_file`, `write_file` * | Files |
| `get_clipboard`, `set_clipboard` | Clipboard |
| `power` * | lock, sleep*, shutdown*, restart*, cancel |

**Apps (`jarvis_apps.py`)**

| Tool | Does |
|---|---|
| `list_installed_apps`, `open_installed_app` | Any app from the Start Menu, fuzzy name match |
| `whatsapp_send` | WhatsApp Web message (scan the QR code once) |
| `gmail_check` | Reads recent inbox subject lines (log in once) |
| `spotify_play` | Opens Spotify (app or web) with your search; you press play |

**Phone (`jarvis_phone.py`)**

| Tool | Does |
|---|---|
| `phone_wake`, `phone_unlock` | Wake the screen; optionally type a PIN |
| `phone_home`, `phone_back` | Navigation keys |
| `phone_list_apps`, `phone_open_app` | List and open apps (WhatsApp, YouTube, Chrome, Gmail, Instagram, Camera, Settings, Spotify have short names) |
| `phone_screenshot` | Saves a screenshot to `Pictures` |
| `phone_type_text`, `phone_tap`, `phone_swipe` | Input |

---

## Configuration reference

Settings are plain variables at the top of each file.

**`jarvis.py`**

| Setting | Default | Meaning |
|---|---|---|
| `WAKE_WORD` | `"jarvis"` | Word that wakes Jarvis in wake word mode. A few mishearings (jervis, jarwis...) also count (`WAKE_ALIASES`). |
| `OLLAMA_MODEL` | `"llama3.2:3b"` | AI model. Try `qwen2.5:7b` for better Tamil, `llama3.2:1b` for slow laptops. |
| `VOICE` | `"en-GB-RyanNeural"` | English voice |
| `VOICE_TANGLISH` | `"en-IN-PrabhatNeural"` | Voice for Tanglish replies |
| `SPEECH_LANGUAGES` | `"both"` | `"both"` = English + Tamil/Tanglish. `"en"` = English only (a little faster). |
| `WHISPER_GPU_MODEL` | `"medium"` | Speech model on the GPU. Use `"small"` if GPU memory is low. |
| `WHISPER_CPU_MODEL` | `"small"` | Speech model if the GPU cannot be used |
| `TAMIL_LEAN` | `0.5` | Lower = Jarvis switches to Tamil more easily |
| `PUSH_TO_TALK` | `True` | Hold a key to talk |
| `PTT_KEY` | `"copilot"` | Talk key. `"copilot"` = the Copilot key (hold, or tap-start / tap-stop). Any other name (`"f8"`, `"caps lock"`, `"right ctrl"` ...) = hold to talk. |
| `TAP_SECONDS` | `0.25` | Copilot key: a press shorter than this counts as a tap |
| `NOISE_REDUCE` | `True` | Clean background murmur from each recording |
| `ANNOUNCE_DEVICES` | `True` | Speak device connect/disconnect events |
| `ACTIVE_WINDOW` | `30` | Seconds Jarvis keeps listening after the wake word |
| `MIN_SPEECH_FRAMES` | `8` | Ignore clips shorter than about 0.8 s (wake word mode) |
| `ONLINE_VOICE_TIMEOUT` | `6` | Seconds to wait for `edge-tts` before using the offline voice |
| `HEADSET_WORDS` | headset, buds, usb ... | A newly appearing microphone whose name contains one of these is picked automatically |
| `APPS` | notepad, calculator, chrome, vscode | Allow-list for the simple `open_app` tool |
| `SYSTEM` | butler prompt | The AI's personality and rules. It currently calls the user "sir" and names "Ezhil" - change the name here. |

**`jarvis_hud_pro.py`**: `HIDE_DELAY` (8 s after Jarvis finishes), `SCALE` (overall size), `DIM_SCREEN` (edge darkening, 0 = off), `FPS` (30; lower it on a slow PC), `TYPE_CPS` (typing speed), `SHOW_CLOCK`, `SHOW_STATS`, `SHOW_CORNERS`, `FONT_HEAD`, `FONT_BODY`, and the state colours (`C_CYAN`, `C_GREEN`, `C_AMBER`, `C_SPEAK`).

**`jarvis_hud.py`**: `IMAGE_FILE` (`ironman.png`), `PANEL_WIDTH`, `HIDE_DELAY` (4 s after Jarvis finishes talking), `PTT_RELEASE_TIMEOUT` (6 s), `TYPE_SECONDS_PER_CHAR`, `SLIDE_IN`, `SLIDE_OUT`, and the colours.

**`jarvis_devices.py`**: `POLL_SECONDS` (4), `SETTLE_SECONDS` (1.5), `DEDUP_SECONDS` (10), `PS_CLASSES` (device types watched).

**`jarvis_phone.py`**: `PHONE_PIN` (empty by default), `KNOWN_APPS` (app name to Android package).

**`jarvis_mobile.py`**: `SECRET` (change it!), port `5000`.

---

## Feature details

### Speech recognition (English + Tamil/Tanglish)
Whisper first detects whether the recording is English or Tamil. English is transcribed directly. For Tamil (including Tamil mixed with English words) Whisper's *translate* mode produces English text, so the wake word, the instant commands, the tools and the AI all keep working in English. The AI is then told to reply in Tanglish. Tamil needs a bigger Whisper model than English, so the default is `medium` on the GPU (`small` on the CPU).

### Noisy rooms
1. **Push-to-talk** is the strongest fix: only the key-held audio is used.
2. **Noise reduction** (`noisereduce`) cleans each recording before transcription.
3. In wake word mode the microphone threshold is **calibrated** at start and keeps **adapting** to the room noise.
4. Clips that are too short, and typical Whisper hallucinations on silence ("Thank you", "Bye", ...) are thrown away.
5. Best of all: use a **wired headset** and keep the mic close to your mouth.

### Voice output
`edge-tts` gives a natural voice but needs internet. If it fails or takes more than 6 seconds, Jarvis uses the built-in Windows voice and keeps using it for the next 2 minutes, so replies are not delayed. This also lets Jarvis announce "Wi-Fi disconnected".

### GPU use
- **Ollama** uses the NVIDIA GPU automatically. Check with `ollama ps` while Jarvis runs: `PROCESSOR` should say `100% GPU`.
- **Whisper** tries the GPU first (`int8_float16`). It needs the pip packages `nvidia-cublas-cu12` and `nvidia-cudnn-cu12`; `jarvis.py` finds their DLLs in `site-packages\nvidia\*\bin` by itself. If the GPU fails, Jarvis switches to the CPU model and keeps working.

### Device announcements and microphone switching
`jarvis_devices.py` checks every 4 seconds and speaks about changes: audio devices (headphones, earbuds, speakers), connected Bluetooth devices (read from the Windows Bluetooth API, so only really connected devices count), phones, USB drives, cameras, printers, mouse, keyboard, external displays, Wi-Fi connect/disconnect/switch, and charger plugged/unplugged. One physical device is announced once ("HUAWEI FreeBuds 5" and "HUAWEI FreeBuds 5 Hands-Free" are the same earbuds).

When an audio device appears or disappears, Jarvis re-scans the audio hardware a few times (Bluetooth microphones can take several seconds to show up). If a headset-like microphone appears, Jarvis switches to it and says "Microphone switched to ..."; when it is unplugged Jarvis goes back to the normal microphone. If the picked microphone cannot be opened, Jarvis falls back to the default one.

### The HUD
**HUD Pro** (`jarvis_hud_pro.py`) is a see-through, click-through overlay over the whole screen. While you talk it fades in:
- a glowing **orb** with rotating rings; the waveform ring follows your real microphone volume. Green = LISTENING, amber = THINKING (comets orbit), cyan = SPEAKING (ripples)
- a **glass panel** with what you said and Jarvis's reply typed out, the language (EN or TA > EN), the microphone in use and an equalizer
- **clock**, date, **CPU / RAM / battery** meters and glowing corner brackets

It fades away `HIDE_DELAY` seconds after Jarvis finishes. It never takes keyboard focus. It appears when you press the talk key, when Jarvis answers, and for device announcements. It needs `PySide6` and Windows. The look was checked by rendering it off-screen on dark and bright wallpapers; on the real PC, run it and adjust `SCALE` / `DIM_SCREEN` to taste.

The **classic HUD** (`jarvis_hud.py`): Iron Man slides in from the right edge when you press the talk key, with the same panel, equalizer bars and CPU/RAM meters, and slides away four seconds after Jarvis finishes. It needs `ironman.png` in the same folder.

### Wake word helpers
`has_wake(text)` and `strip_wake(text)` in `jarvis.py` detect and remove the wake word (including common mishearings). Other files, like the HUD, use them.

---

## Phone control (ADB)

Jarvis talks to an Android phone through **ADB (Android Debug Bridge)**.

### One-time setup
1. Phone: **Settings > About phone**, tap **Build number** 7 times to unlock Developer options.
2. Phone: **Settings > Developer options > USB debugging: ON**.
3. Laptop: download **SDK Platform-Tools** from developer.android.com (search "platform-tools"), extract to `C:\platform-tools`, and add that folder to the **PATH** (Environment Variables). Open a new terminal.
4. Connect the phone with a USB cable, choose **File transfer** mode, tap **Allow** on the phone's USB debugging popup.
5. Check:

```
adb devices
```

Your phone must show as `device`.

### Without a cable (Wi-Fi)
**Android 11 or newer (Wireless debugging):** turn on *Wireless debugging* in Developer options, tap *Pair device with pairing code*, then

```
adb pair <IP>:<pairing-port>
adb connect <IP>:<port-shown-on-the-main-screen>
```

Phone and laptop must be on the same Wi-Fi.

**Cable first, then wireless (works on older phones too, and is more stable):**

```
adb tcpip 5555
adb connect <phone-IP>:5555
```

Then unplug the cable. If the phone's IP changes or the connection drops, run `adb connect <phone-IP>:5555` again.

*Known issue:* on some phones (for example Vivo/Origin OS) the *Wireless debugging* switch turns itself off after a while or when the screen locks. The `adb tcpip 5555` method avoids this.

### Unlocking
`phone_unlock` wakes the screen and swipes up. If you put your PIN in `PHONE_PIN` in `jarvis_phone.py`, Jarvis types it. That PIN is then stored as plain text on your PC, so leave it empty unless you accept that. Fingerprint and face unlock cannot be done by Jarvis.

### Phone commands over Wi-Fi from the phone side
`jarvis_mobile.py` (needs `flask`) starts a small server on port 5000 so an Android app such as **Tasker** can send a command to Jarvis:

```
POST http://<laptop-IP>:5000/ask
Header:  X-Jarvis-Key: <your SECRET>
Body:    {"text": "what time is it"}
Reply:   {"reply": "..."}
GET  http://<laptop-IP>:5000/health
```

Change `SECRET` before using it. The full Tasker steps are in the comments at the top of the file.

---

## Start automatically when Windows starts

1. Put `start_jarvis.vbs` in `C:\jarvis`. Open it in Notepad and check the two lines marked `CHANGE` (the folder, and `jarvis_hud_pro.py`).
2. Press `Win + R`, type `shell:startup`, press Enter, and copy `start_jarvis.vbs` into that folder.
3. Restart (or sign out and in).

What happens: the file first writes the time into `C:\jarvis\startup_check.txt`, waits 30 seconds (Windows is busy right after login), then starts Jarvis hidden. Everything Jarvis prints goes to `C:\jarvis\jarvis_log.txt`. If Ollama is not running yet, Jarvis waits for it and starts `ollama serve` itself after about 20 seconds. To stop Jarvis, end `python.exe` in Task Manager.

**If a different HUD appears at login than the one you start by hand** (or two Jarvis start), an old start-up item is still there. Run `py -3.12 fix_startup.py`: it moves every old Jarvis item out of the Startup folder into `C:\jarvis\old_startup_backup` (nothing is deleted), installs the new `start_jarvis.vbs`, lists any Task Scheduler / registry entries that also start Jarvis, shows which Jarvis programs are running and offers to stop them. Then restart. It saves a report in `startup_report.txt`.

**If Jarvis does not start at login, check in this order:**
1. Double-click `run_jarvis.bat`. If Jarvis starts and talks, the problem is only the auto-start. If it fails, read the error in that window.
2. Open `startup_check.txt` after logging in. A new line with today's time means Windows ran the file (then read `jarvis_log.txt`). No new line means Windows did not run it: check that the file is in `shell:startup`, and in Task Manager > **Startup apps** that `start_jarvis` is **Enabled** (Windows can switch it off).
3. Open `jarvis_log.txt` and read the last lines (for example Ollama or a missing library).

**Backup method (Task Scheduler).** Open Command Prompt **as administrator** and run (change the path if needed):

```
schtasks /create /tn "Jarvis" /tr "wscript.exe \"C:\jarvis\start_jarvis.vbs\"" /sc onlogon /delay 0000:30 /f
```

Use only one of the two methods, otherwise Jarvis starts twice. Remove the task with `schtasks /delete /tn "Jarvis" /f`.

---

## Extending Jarvis

### Add a tool
In any extension file (or a new one that does `import jarvis`):

```python
import jarvis

def battery_saver_on():
    ...
    return "Battery saver is on"

jarvis.register_tool(
    "battery_saver_on",
    battery_saver_on,
    '{}  -- Turn on battery saver.',      # arguments + what the tool does (the AI reads this)
)
```

Arguments arrive as keyword arguments, so a tool described as `{"name": str}` is a function `def tool(name): ...`. Return a short text: the AI reads it and answers with it.

### Add an instant command (skips the AI, so it is immediate)

```python
def good_morning():
    return "Good morning, sir. Have a great day."

jarvis.FAST_COMMANDS.append((("good morning", "wake up"), good_morning))
```

If any phrase is heard, the function runs; if it returns text, Jarvis speaks it. The function may also accept one argument to receive the sentence.

### Load it
Import your file from `jarvis_hud.py` (or run it with `jarvis.main()` at the bottom, like the other extensions).

---

## Safety and privacy

- **Local first:** speech recognition and the AI run on your PC. Only these leave it: the text of Jarvis's replies sent to Microsoft's `edge-tts` service for the voice, web searches, and WhatsApp/Gmail traffic.
- **Confirmation:** `run_command`, `write_file` and `power` (sleep, shutdown, restart) ask for a spoken "yes". A misheard "yes" would also count, so be careful with these tools.
- **Blocked commands:** a few obviously destructive patterns (`rm -rf /`, `format c:`, ...) are refused.
- **Emergency stop for the mouse/keyboard tools:** move the mouse into any screen corner (PyAutoGUI fail-safe).
- **The AI can make mistakes.** A small model may pick a wrong tool. The prompt tells it to use tools only for clear requests, but do not give it access to anything you cannot afford to lose.
- **Always-on microphone:** in wake word mode Jarvis processes sound continuously (locally). Push-to-talk only records while the key is held.
- **WhatsApp/Gmail** are automated through a Chrome profile stored in `C:\Users\<you>\.jarvis_chrome_profile`. It contains your logged-in sessions, so keep that folder private.
- **`PHONE_PIN`** and the **`SECRET`** of `jarvis_mobile.py` are plain text in the files. Do not share those files after filling them in. The mobile bridge is plain HTTP on your local Wi-Fi.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `python` opens the Microsoft Store or says "Python was not found" | Use `py -3.12 ...` instead of `python ...`. |
| `pygame` fails to build / "Failed to build wheel" | You are on Python 3.14. Install 3.12 (`py install 3.12`) and use `py -3.12`. |
| `ModuleNotFoundError: No module named 'xyz'` | `py -3.12 -m pip install xyz` (use the same Python you run Jarvis with). |
| Copying/pasting (Ctrl+C / Ctrl+V) makes the HUD pop up | The talk key was Right Ctrl. It is now the Copilot key (`PTT_KEY = "copilot"`). |
| The Copilot key opens Copilot instead of talking to Jarvis, or nothing happens | Run `py -3.12 test_copilot_key.py` and press the key: you should see `f23`. If you do not, your keyboard sends something else: use another key (`PTT_KEY = "f8"`). If the key only taps, tap once to start and again to stop. |
| A different HUD appears at login than the one I run by hand | Old start-up entry. Run `py -3.12 fix_startup.py`, then restart. |
| Jarvis does not start when I log in | See *Start automatically*: `run_jarvis.bat`, then `startup_check.txt`, then `jarvis_log.txt`. |
| `This HUD needs PySide6` | `py -3.12 -m pip install PySide6` |
| HUD Pro prints `OverflowError` / `endPaint` lines | Old `jarvis_hud_pro.py`. Replace it with the latest file. |
| `qt.qpa.window: SetProcessDpiAwarenessContext() failed` | Harmless notice (pygame set the screen scaling first). The latest `jarvis_hud_pro.py` hides it. |
| `RuntimeError: Library cublas64_12.dll is not found` | GPU libraries missing. Run `py -3.12 -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`. Jarvis also switches to the CPU by itself and keeps working. |
| `module 'jarvis' has no attribute '...'` (for example `register_tool`, `FAST_COMMANDS`, `has_wake`) | Files from different versions are mixed. Replace **all** Jarvis files with matching versions, delete the `__pycache__` folder, run again. |
| `jarvis.py is an OLD version (missing: ...)` | Same as above. |
| Jarvis does not react / "YOU:" never appears | Check the microphone (Windows Settings > System > Sound > Input). Run `py -3.12 test_mic.py`: silence should be near 0.00x and speech clearly higher. Reduce Windows mic boost and turn off "enhancements". |
| "Ambient noise" at calibration is very high (like 0.2) | Mic gain is too high, or the wrong input device. Lower the gain, or use push-to-talk (no calibration needed). |
| Whisper writes random sentences ("thank you", "see you in the next video") | It is hearing noise. Use push-to-talk, a headset, noise reduction on, and speak close to the mic. |
| Jarvis reads out `{"tool": ...}` | Old `jarvis.py`. The current one understands several JSON shapes and never speaks raw JSON. |
| Reply is very slow | Run `ollama ps` while Jarvis runs; it should show `100% GPU`. Use a smaller `OLLAMA_MODEL` or `WHISPER_GPU_MODEL`. The first question after start-up is slower (model loading). Right after a Windows restart everything is slower, so delay the auto-start by about 60 seconds. |
| `(online voice unavailable: TimeoutError ...)` | `edge-tts` cannot connect. Update it (`py -3.12 -m pip install -U edge-tts`) and check the internet. Jarvis uses the Windows voice meanwhile. |
| The voice sounds robotic | That is the offline Windows voice (fallback). See the line above. |
| Wrong Tamil recognition | Use `WHISPER_GPU_MODEL = "medium"`, speak clearly and closer to the mic, lower `TAMIL_LEAN` (for example 0.3). |
| Tanglish replies are poor | The 3B model is weak in Tamil. Try `OLLAMA_MODEL = "qwen2.5:7b"`. |
| `adb` is not recognized | Add `C:\platform-tools` to PATH and open a new terminal. |
| `adb devices` shows `unauthorized` | Unlock the phone and tap Allow on the USB debugging popup. |
| Wireless debugging switches off by itself | Use `adb tcpip 5555` + `adb connect <IP>:5555` (see Phone control). |
| Device announcements name devices that are not connected | Update to the latest `jarvis_devices.py`; it reads real Bluetooth connection state. |
| The mic did not switch when I connected earbuds | In Windows Sound settings check that the earbuds' microphone shows up. It can take a few seconds for Bluetooth. The microphone name must contain a word from `HEADSET_WORDS`. |
| HUD does not appear | Run `jarvis_hud_pro.py` (needs PySide6) or `jarvis_hud.py` (needs `ironman.png` next to it). Press the talk key; it also appears whenever Jarvis speaks. |
| WhatsApp/Gmail tool says "not logged in" | Log in or scan the QR code in the Chrome window that Jarvis opened, then ask again. |
| Auto-start does not work | Check the file is in `shell:startup`, look at `jarvis_log.txt`, check Ollama is in the system tray, and confirm the path in the `.vbs`. |

---

## Status: what is tested and what is not

**Run and working on the developer's laptop (seen working):**
- Whole voice loop: microphone, Whisper, Ollama, spoken reply, tools such as `get_time`
- Ollama on the NVIDIA GPU (`100% GPU`)
- Mic calibration, English recognition, auto fallback to the CPU when the GPU libraries fail
- Classic Iron Man HUD display
- Device announcements (the first version worked; the "paired but not connected" and "name twice" problems were fixed afterwards)
- Offline voice fallback

**Written and checked with simulated hardware only (not yet confirmed on a real PC):**
- Tamil/Tanglish pipeline (language detection, translate mode, Tanglish replies, Indian voice)
- GPU Whisper with the corrected DLL folders
- Windows Bluetooth API connection check
- Automatic switching to a headset microphone
- Tool-call parsing for the different JSON shapes, tool error handling, `FAST_COMMANDS`, `register_tool`

- **HUD Pro**: drawn and checked off-screen (dark and bright wallpapers, every state, running for months of animation time). An `OverflowError` found on the real PC was fixed; the fixed file has not been seen running on the real PC yet
- **Copilot key as the talk key**: the hold / tap / swallow logic is tested with simulated key events and the `keyboard` library's code was read, but it has not been tried on a real Copilot key. Some laptops send the key as a quick tap, which is why tap-start / tap-stop is supported
- **Start at login**: waiting for Ollama, starting `ollama serve`, surviving errors and the new `start_jarvis.vbs` are tested in simulation; the real login behaviour is not confirmed yet

**Not tested by the author at all:**
- WhatsApp, Gmail and Spotify tools
- Phone commands after ADB setup
- `jarvis_mobile.py` with Tasker

The classic HUD (`jarvis_hud.py`, Iron Man slide-in with `ironman.png`) was written separately from the other files; this README describes it from its settings and comments.

If something fails, copy the **exact** error text from the terminal. The error message is what identifies the problem.

---

## Ideas for later

- Show the list of connected devices in the HUD
- Typed commands (useful when speaking is not possible, such as in class)
- Calendar, mail and task dashboards
- Raspberry Pi version with sensors, servos and relays (smart home)
- Face recognition with OpenCV ("Welcome back, sir")
- Hand-gesture control with MediaPipe

---

## Built with

[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (speech recognition), [Ollama](https://ollama.com) with Llama 3.2 (AI), [edge-tts](https://github.com/rany2/edge-tts) (voice), [pygame](https://www.pygame.org), [sounddevice](https://python-sounddevice.readthedocs.io), [noisereduce](https://github.com/timsainb/noisereduce), [keyboard](https://github.com/boppreh/keyboard), [PyAutoGUI](https://pyautogui.readthedocs.io), [Selenium](https://www.selenium.dev), [psutil](https://github.com/giampaolo/psutil), [Flask](https://flask.palletsprojects.com), Android Debug Bridge, tkinter (HUD).

Author: *(add your name here)*
