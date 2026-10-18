"""
JARVIS (FREE / LOCAL, auto-calibrating mic): Mic -> Whisper -> Ollama -> TTS -> Speaker

ONE-TIME SETUP:
  1. Install Ollama: https://ollama.com
  2. ollama pull llama3.2:3b
  3. py -3.12 -m pip install faster-whisper sounddevice numpy edge-tts pygame psutil requests

RUN:
  py -3.12 jarvis_apps.py     (full version, run this one)
  py -3.12 jarvis.py          (core only, for testing)

Say: "Jarvis, what time is it?"
"""
import asyncio
import datetime
import glob
import inspect
import json
import os
import re
import subprocess
import sys
import threading
import tempfile
import time
import urllib.parse
import webbrowser

# Let faster-whisper find the NVIDIA GPU libraries installed with pip
# (nvidia-cublas-cu12, nvidia-cudnn-cu12). They live in site-packages\nvidia\<lib>\bin.
if sys.platform == "win32":
    for _site in sys.path:
        for _bin in glob.glob(os.path.join(_site, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(_bin)
            except OSError:
                pass
            os.environ["PATH"] = _bin + os.pathsep + os.environ.get("PATH", "")

import edge_tts
import numpy as np
import psutil
import pygame
import requests
import sounddevice as sd
from faster_whisper import WhisperModel

try:
    import noisereduce as nr      # background-noise suppression
except ImportError:
    nr = None
try:
    import keyboard               # push-to-talk key
except ImportError:
    keyboard = None

# ---------- CONFIG ----------
WAKE_WORD = "jarvis"
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.2:3b"
VOICE = "en-GB-RyanNeural"
VOICE_TANGLISH = "en-IN-PrabhatNeural"   # Indian-English voice reads Tanglish (Tamil in English letters) best

# ----- LANGUAGES: English + Tamil/Tanglish -----
SPEECH_LANGUAGES = "both"    # "both" = understand English AND Tamil/Tanglish.  "en" = English only (a bit faster)
WHISPER_GPU_MODEL = "medium" # Tamil needs a bigger model than "base". Low on GPU memory? try "small"
WHISPER_CPU_MODEL = "small"  # used if the GPU can't be used
TAMIL_LEAN = 0.5             # lower = switches to Tamil more easily (Tanglish often sounds "English" to Whisper)
_lang = "en"                 # language of the last thing you said: "en" or "ta"
SR = 16000
ACTIVE_WINDOW = 30
MIN_SPEECH_FRAMES = 8

# ----- NOISY ROOM SETTINGS (classroom, etc.) -----
PUSH_TO_TALK = True      # hold PTT_KEY while speaking; everything else is ignored
PTT_KEY = "copilot"      # the Copilot key: hold it while you speak, OR tap once to start and tap again to stop.
                         # Any other key name works too (hold to talk): "right ctrl", "f8", "caps lock", "space" ...
TAP_SECONDS = 0.25       # Copilot key: a press shorter than this counts as a "tap" (tap = start / stop)
NOISE_REDUCE = True      # strip background murmur from your recording before transcribing
ANNOUNCE_DEVICES = True  # speak when headset / Bluetooth / USB / Wi-Fi / charger connects or disconnects
# Phrases Whisper commonly hallucinates from silence/noise -- filtered out.
JUNK_PHRASES = {
    "thank you", "thank you.", "thanks for watching", "thanks for watching!",
    "bye", "bye.", "bye bye", "you", "you.", "i'm going to go", "okay",
    "so", "subscribe", "the end", ".",
}
SYSTEM = (
    "You are JARVIS, a witty, polite British AI butler for Ezhil. "
    "Address him as 'sir'. Keep replies to 1-2 short spoken sentences. "
    "When a tool would help, your ENTIRE response must be ONLY the raw JSON "
    'object, nothing else, no explanation, no extra words: {"tool": "<name>", "args": {...}}. '
    "Never mix JSON with spoken text in the same reply. "
    "Once you have a tool's result, answer the user in plain spoken sentences "
    "using that real result -- never invent or guess a result yourself. "
    "Only use a tool when the user clearly asks you to DO something on the computer. "
    "For questions, small talk, or speech that is unclear, answer in words "
    "(or ask them to repeat) -- never guess a tool."
)

APPS = {
    "notepad": "notepad",
    "calculator": "calc",
    "chrome": "chrome",
    "vscode": "code",
}

print("Loading speech model... (the first run downloads it, please wait)")


def _load_stt():
    try:
        m = WhisperModel(WHISPER_GPU_MODEL, device="cuda", compute_type="int8_float16")
        print(f"Speech model '{WHISPER_GPU_MODEL}' running on GPU.")
        return m
    except Exception as e:
        print(f"GPU load failed ({e}), falling back to CPU.")
        return WhisperModel(WHISPER_CPU_MODEL, device="cpu", compute_type="int8")


stt = _load_stt()
pygame.mixer.init()


# ---------- AUTO-CALIBRATE MIC (no more manual guessing) ----------
def calibrate_mic(seconds=2.0):
    print(f"Calibrating mic -- stay quiet for {seconds:.0f} seconds...")
    block = int(SR * 0.1)
    levels = []
    with sd.InputStream(device=_mic_device, samplerate=SR, channels=1, dtype="float32", blocksize=block) as stream:
        for _ in range(int(seconds / 0.1)):
            data, _ = stream.read(block)
            levels.append(float(np.sqrt(np.mean(data ** 2))))
    ambient = max(levels) if levels else 0.002
    threshold = max(ambient * 4, 0.006)
    print(f"Ambient noise: {ambient:.4f} -> using threshold: {threshold:.4f}")
    return threshold


SILENCE_RMS = 0.01  # placeholder, replaced by calibrate_mic() in main()


# ---------- TOOLS ----------
def get_time():
    return datetime.datetime.now().strftime("%A, %d %B %Y, %I:%M %p")


def open_app(name):
    cmd = APPS.get(name.lower())
    if not cmd:
        return f"App '{name}' not in allowed list: {list(APPS)}"
    subprocess.Popen(cmd, shell=True)
    return f"Opened {name}"


def web_search(query):
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query))
    return f"Searching Google for {query}"


def play_youtube(query):
    webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query))
    return f"Opened YouTube results for {query}"


def system_status():
    b = psutil.sensors_battery()
    return (
        f"CPU {psutil.cpu_percent()}%, RAM {psutil.virtual_memory().percent}%, "
        f"battery {round(b.percent) if b else 'N/A'}%"
    )


TOOL_FUNCS = {
    "get_time": lambda **kw: get_time(),
    "open_app": lambda **kw: open_app(kw["name"]),
    "web_search": lambda **kw: web_search(kw["query"]),
    "play_youtube": lambda **kw: play_youtube(kw["query"]),
    "system_status": lambda **kw: system_status(),
}

TOOL_HELP = (
    "Available tools:\n"
    "- get_time {}\n"
    "- open_app {\"name\": one of " + str(list(APPS)) + "}\n"
    "- web_search {\"query\": str}\n"
    "- play_youtube {\"query\": str}\n"
    "- system_status {}\n"
)


def register_tool(name, fn, desc=""):
    """Extension files (desktop / apps / phone) call this to add a tool.
    desc looks like:  '{"arg": str}  -- what the tool does'"""
    global TOOL_HELP
    TOOL_FUNCS[name] = (lambda f: (lambda **kw: f(**kw)))(fn)
    TOOL_HELP += f"- {name} {desc}\n"


# Instant voice commands that skip the AI. Extension files add entries like:
#   jarvis.FAST_COMMANDS.append((("wake up", "good morning"), my_routine))
# my_routine() runs when any phrase is heard; if it returns text, Jarvis speaks it.
FAST_COMMANDS = []


def _run_fast_command(text):
    low = text.lower()
    for phrases, fn in FAST_COMMANDS:
        if any(p in low for p in phrases):
            try:
                needs_arg = any(
                    p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                    for p in inspect.signature(fn).parameters.values()
                )
                result = fn(text) if needs_arg else fn()
            except Exception as e:
                result = f"Sorry sir, that routine failed: {e}"
            if isinstance(result, str) and result:
                speak(result)
            return True
    return False


# ---------- WAKE WORD ----------
# Whisper sometimes hears "Jarvis" a little differently, so a few close spellings count too.
WAKE_ALIASES = ("jarvice", "jarviss", "jervis", "jarwis", "jarves", "charvis")


def _wake_match(text):
    low = text.lower()
    for w in (WAKE_WORD,) + WAKE_ALIASES:
        i = low.find(w)
        if i != -1:
            return i, w
    return None


def has_wake(text):
    """True if the wake word ("Jarvis", or a close mishearing) is in the text."""
    return _wake_match(text) is not None


def strip_wake(text):
    """Everything said after the wake word (the text unchanged if there is none)."""
    m = _wake_match(text)
    if not m:
        return text
    i, w = m
    return text[i + len(w):].strip(" ,.!?")


# ---------- BRAIN (Ollama, local, free) ----------
history = []


def _ollama_chat(messages):
    r = requests.post(
        OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["message"]["content"]


def wait_for_ollama(max_wait=240):
    """Right after Windows login Ollama may not be running yet. Wait for it instead of crashing."""
    base = OLLAMA_URL.split("/api/")[0]
    start, tried_launch, told = time.time(), False, False
    while time.time() - start < max_wait:
        try:
            requests.get(base, timeout=2)
            if told:
                print("Ollama is ready.")
            return True
        except Exception:
            if not told:
                print("Waiting for Ollama to start...")
                told = True
            if not tried_launch and time.time() - start > 20:     # the tray app had its chance; start it ourselves
                tried_launch = True
                print("Ollama is still not running -- starting it...")
                try:
                    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                except Exception:
                    pass                       # not on PATH / already starting: keep waiting
            time.sleep(3)
    print("Ollama did not start. Open Ollama from the Start menu; Jarvis will use it as soon as it runs.")
    return False


_LANG_RULE = {
    "en": "Reply in English.",
    "ta": ("The user is speaking Tamil/Tanglish, so reply in Tanglish: Tamil written in English letters, mixed "
           "with common English words, like 'Ippo time 7:35 PM, sir.' or 'Notepad open pannitten, sir.' or "
           "'Seri sir, Chrome open pannuren.' Keep it 1-2 short sentences. Tool JSON must stay in English."),
}

_ARG_KEYS = ("args", "arguments", "parameters", "input")


def _parse_tool_call(reply):
    """Find a tool call in the model's reply -> (name, args) or None.
    Accepts {"tool": "x", "args": {...}} and the other shapes small models like to use:
    {"open_app": {"name": "chrome"}}  or  {"name": "open_app", "arguments": {...}}."""
    start, end = reply.find("{"), reply.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(reply[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None

    def args_of(d):
        for k in _ARG_KEYS:
            if k in d:
                a = d[k]
                if isinstance(a, str):
                    try:
                        a = json.loads(a) if a.strip() else {}
                    except json.JSONDecodeError:
                        a = {}
                return a if isinstance(a, dict) else {}
        return {}

    if isinstance(obj.get("tool"), str):
        return obj["tool"], args_of(obj)
    for key in ("name", "function", "tool_name"):
        if isinstance(obj.get(key), str) and obj[key] in TOOL_FUNCS:
            return obj[key], args_of(obj)
    if len(obj) == 1:
        (name, a), = obj.items()
        if name in TOOL_FUNCS:
            return name, (a if isinstance(a, dict) else {})
    return None


def think(user_text):
    history.append({"role": "user", "content": user_text})
    system_msg = {"role": "system", "content": SYSTEM + "\n" + _LANG_RULE.get(_lang, _LANG_RULE["en"]) + "\n" + TOOL_HELP}
    for _ in range(4):
        try:
            reply = _ollama_chat([system_msg] + history)
        except Exception as e:
            print(f"(Ollama problem: {type(e).__name__}: {e})")
            return "Sorry sir, I can't reach my AI brain right now. Is Ollama running?"
        history.append({"role": "assistant", "content": reply})

        call = _parse_tool_call(reply)
        if not call:
            text = reply.strip()
            if text.startswith("{") and text.endswith("}"):
                return "Sorry sir, I didn't understand that one. Could you say it again?"  # never read JSON aloud
            return text

        name, args = call
        fn = TOOL_FUNCS.get(name)
        try:
            result = fn(**args) if fn else f"Unknown tool: {name}"
        except TypeError as e:
            result = f"Bad arguments for {name}: {e}"
        except Exception as e:
            result = f"Tool {name} failed: {e}"
        history.append({"role": "user", "content": f"[Tool result for {name}]: {result}"})
    return "Sorry sir, I couldn't complete that."


# ---------- VOICE ----------
_speak_lock = threading.RLock()     # one voice at a time (main thread + device watcher)
_mic_dirty = threading.Event()      # set by the device watcher when audio hardware changed
_last_mic = [None]
_online_voice_down_until = 0.0      # edge-tts failed recently -> use the offline voice for a while
ONLINE_VOICE_TIMEOUT = 6            # seconds to wait for edge-tts before giving up


def _speak_offline(text):
    """Windows' built-in voice. Works with no internet (used when edge-tts can't connect)."""
    try:
        safe = text.replace("'", "''")
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Add-Type -AssemblyName System.Speech; "
             f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{safe}')"],
            timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        print(f"(offline voice failed: {e})")


def _current_voice():
    return VOICE_TANGLISH if _lang == "ta" else VOICE


def speak(text):
    global _online_voice_down_until
    print("JARVIS:", text)
    with _speak_lock:
        if time.time() < _online_voice_down_until:
            _speak_offline(text)               # online voice failed a moment ago: don't wait again
            return
        try:
            path = os.path.join(tempfile.gettempdir(), "jarvis_tts.mp3")

            async def _tts():
                await asyncio.wait_for(edge_tts.Communicate(text, _current_voice()).save(path),
                                       timeout=ONLINE_VOICE_TIMEOUT)

            asyncio.run(_tts())
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            pygame.mixer.music.unload()
        except Exception as e:
            _online_voice_down_until = time.time() + 120
            print(f"(online voice unavailable: {type(e).__name__} -- using offline voice for the next 2 minutes)")
            _speak_offline(text)


# ---------- MICROPHONE CHOICE (follows your headset) ----------
_mic_device = None      # None = whatever Windows says is the default mic; else a device index
_mic_name = None        # the mic we picked ourselves (so we notice when it is unplugged)
_known_inputs = None    # microphone names seen at the last scan
HEADSET_WORDS = ("headset", "headphone", "earphone", "earbud", "buds", "hands-free", "handsfree",
                 "bluetooth", "usb")


def _input_devices():
    """{name: index} of real microphones on the default audio API."""
    mics = {}
    try:
        host = sd.default.hostapi
        for i, dev in enumerate(sd.query_devices()):
            n = dev["name"]
            if (dev["hostapi"] == host and dev["max_input_channels"] > 0
                    and "sound mapper" not in n.lower() and "primary sound" not in n.lower()):
                mics[n] = i
    except Exception as e:
        print(f"Could not list microphones ({e})")
    return mics


def _choose_mic(mics):
    """After a re-scan: switch to a headset mic that just appeared; go back when it is unplugged."""
    global _known_inputs, _mic_device, _mic_name
    new = [n for n in mics if _known_inputs is not None and n not in _known_inputs]
    _known_inputs = set(mics)
    headset = [n for n in new if any(w in n.lower() for w in HEADSET_WORDS)]
    if headset:                                   # earbuds/headset connected: use its mic
        _mic_name = headset[0]
        _mic_device = mics[_mic_name]
    elif _mic_name and _mic_name not in mics:     # the mic we picked was unplugged
        _mic_name = _mic_device = None
    elif _mic_name:                               # still there; its index may have moved
        _mic_device = mics[_mic_name]


def _init_mics():
    global _known_inputs
    _known_inputs = set(_input_devices())
    try:
        _last_mic[0] = sd.query_devices(kind="input")["name"]
    except Exception:
        pass


def _spoken_mic(name):
    m = re.search(r"\((.+)\)\s*$", name)
    if m:
        return m.group(1)
    return name.split("(")[0].strip() or name     # names cut short by Windows: "Headset Microphone (HUAWEI Free"


def refresh_audio_devices(announce=True):
    """Re-scan audio hardware; if a headset/earbuds mic just appeared, start using it."""
    with _speak_lock:                      # don't pull the audio device out from under a spoken reply
        try:
            sd._terminate()
            sd._initialize()
        except Exception as e:
            print(f"Audio re-scan failed ({e})")
            return
        try:
            pygame.mixer.quit()
            pygame.mixer.init()
        except Exception as e:
            print(f"Speaker re-init failed ({e})")
    _choose_mic(_input_devices())
    try:
        if _mic_device is not None:
            name = sd.query_devices(_mic_device)["name"]
        else:
            name = sd.query_devices(kind="input")["name"]
    except Exception:
        name = None
    print(f"Active microphone: {name}")
    if announce and name and _last_mic[0] and name != _last_mic[0]:
        speak(f"Microphone switched to {_spoken_mic(name)}, sir.")
    if name:
        _last_mic[0] = name


def _clean_audio(audio):
    """Suppress background murmur/fan noise so Whisper hears mostly your voice."""
    if NOISE_REDUCE and nr is not None and len(audio) > SR // 2:
        try:
            audio = nr.reduce_noise(y=audio, sr=SR, stationary=False, prop_decrease=0.9)
        except Exception as e:
            print(f"Noise reduction skipped ({e})")
    return np.asarray(audio, dtype=np.float32)


def _pick_language(audio):
    """'en' or 'ta' -- which one you spoke (Tanglish counts as Tamil)."""
    if SPEECH_LANGUAGES != "both":
        return "en"
    try:
        _, _, probs = stt.detect_language(audio)
    except (AttributeError, TypeError, ValueError, KeyError):
        return "en"                          # old faster-whisper without language detection
    p = dict(probs)
    ta, en = p.get("ta", 0.0), p.get("en", 0.0)
    return "ta" if ta > 0.15 and ta > TAMIL_LEAN * en else "en"


def _transcribe(audio):
    """Text in English. Tamil/Tanglish speech is translated to English, so the wake word,
    tools and the AI all keep working; Jarvis then answers in Tanglish."""
    global stt, _lang

    def run():
        lang = _pick_language(audio)
        segments, _ = stt.transcribe(
            audio, language=lang, task="translate" if lang == "ta" else "transcribe",
            vad_filter=True, condition_on_previous_text=False, no_speech_threshold=0.6)
        return lang, " ".join(s.text for s in segments).strip()

    try:
        lang, text = run()
    except Exception as e:
        print(f"GPU transcribe failed ({e}), switching to CPU for the rest of this session.")
        stt = WhisperModel(WHISPER_CPU_MODEL, device="cpu", compute_type="int8")
        lang, text = run()
    if text:
        _lang = lang
    return text


# ---------- THE COPILOT KEY AS THE TALK KEY ----------
COPILOT_NAMES = ("copilot", "copilot key", "f23")


def _is_copilot(name):
    return str(name).strip().lower() in COPILOT_NAMES


class _CopilotKey:
    """A laptop's Copilot key sends  Left Win + Left Shift + F23.  We swallow the F23 part so Windows does
    not open Copilot, and use it as the talk key:
      - hold it while you speak (stops when you let go), or
      - tap it once to start and tap it again to stop."""

    def __init__(self):
        self.active = False          # True while Jarvis should be recording
        self.latched = False         # started by a tap, waiting for the second tap
        self.down_at = None
        self.ended_by_press = False

    def on_event(self, event):
        try:
            now = time.time()
            if event.event_type == "down":
                if self.down_at is None:                # ignore the repeats while the key is held
                    self.down_at = now
                    if self.latched:                    # second tap: stop
                        self.latched = False
                        self.active = False
                        self.ended_by_press = True
                    else:
                        self.active = True
            else:
                held = now - self.down_at if self.down_at else 0.0
                self.down_at = None
                if self.ended_by_press:
                    self.ended_by_press = False
                elif held < TAP_SECONDS:                # quick tap: keep recording until the next tap
                    self.latched = True
                else:                                   # it was a hold: stop on release
                    self.active = False
        except Exception:
            pass
        return False                                    # False = Windows never sees this key

    def finish(self):
        self.active = False
        self.latched = False


_copilot = _CopilotKey()
_ptt_ready = False


def _setup_ptt():
    """Start listening to the Copilot key (once)."""
    global _ptt_ready
    if _ptt_ready:
        return
    _ptt_ready = True
    if keyboard is None or not _is_copilot(PTT_KEY):
        return
    codes = {110}                                       # F23's usual scan code (0x6E)
    try:
        codes.update(keyboard.key_to_scan_codes("f23"))
    except Exception:
        pass
    try:
        for code in codes:
            keyboard.hook_key(code, _copilot.on_event, suppress=True)
        print("Copilot key ready: hold it to talk, or tap once to start and tap again to stop.")
    except Exception as e:
        print(f"Could not listen to the Copilot key ({e}). Set PTT_KEY to another key, for example \"f8\".")


def ptt_pressed():
    """True while the talk key is held (Copilot key: held, or switched on by a tap)."""
    if _is_copilot(PTT_KEY):
        _setup_ptt()
        return _copilot.active
    return keyboard.is_pressed(PTT_KEY)


def _record_push_to_talk():
    """Wait until PTT_KEY is pressed, record while it is held, stop on release."""
    block = int(SR * 0.1)
    while not ptt_pressed():
        if _mic_dirty.is_set():            # headset plugged/unplugged while idle
            _mic_dirty.clear()
            refresh_audio_devices()
        time.sleep(0.03)
    frames = []
    with sd.InputStream(device=_mic_device, samplerate=SR, channels=1, dtype="float32", blocksize=block) as stream:
        while ptt_pressed() and len(frames) < 300:  # 30s max
            data, _ = stream.read(block)
            frames.append(data.copy())
    if _is_copilot(PTT_KEY):
        _copilot.finish()                               # also ends a tap-started recording that hit the 30 s limit
    return frames


def _record_vad():
    """Always-listening mode with a noise floor that adapts to murmur levels."""
    block = int(SR * 0.1)
    floor = SILENCE_RMS / 4
    while True:
        frames, started, silent = [], False, 0
        with sd.InputStream(device=_mic_device, samplerate=SR, channels=1, dtype="float32", blocksize=block) as stream:
            while True:
                if _mic_dirty.is_set() and not started:
                    break                  # audio hardware changed: reopen on the new mic
                data, _ = stream.read(block)
                rms = float(np.sqrt(np.mean(data ** 2)))
                threshold = max(SILENCE_RMS, floor * 4)
                if rms > threshold:
                    started, silent = True, 0
                    frames.append(data.copy())
                else:
                    if not started:
                        floor = 0.97 * floor + 0.03 * rms  # track slowly changing room noise
                    if started:
                        frames.append(data.copy())
                        silent += 1
                        if silent > 10 or len(frames) > 150:
                            return frames
        _mic_dirty.clear()
        refresh_audio_devices()


def _use_ptt():
    return PUSH_TO_TALK and keyboard is not None


def listen():
    """Record (push-to-talk or always-listening), clean noise, transcribe. Returns "" if nothing real."""
    global _mic_device, _mic_name
    ptt = _use_ptt()
    try:
        frames = _record_push_to_talk() if ptt else _record_vad()
    except Exception as e:                 # e.g. headset unplugged in the middle of recording
        print(f"Mic error ({e}) -- re-scanning audio devices...")
        if _mic_device is not None:
            print("(the picked mic can't be opened -- going back to the default mic)")
            _mic_device = _mic_name = None
        time.sleep(1)
        _mic_dirty.clear()
        refresh_audio_devices()
        return ""
    if len(frames) < (4 if ptt else MIN_SPEECH_FRAMES):
        return ""
    audio = _clean_audio(np.concatenate(frames).flatten())
    text = _transcribe(audio)
    if text.lower().strip(" .!") in JUNK_PHRASES:
        return ""
    return text


# ---------- MAIN LOOP ----------
def main():
    global SILENCE_RMS
    ptt = _use_ptt()
    if ptt:
        _setup_ptt()
    if PUSH_TO_TALK and keyboard is None:
        print("PUSH_TO_TALK is on but the 'keyboard' library is missing.")
        print("Run:  py -3.12 -m pip install keyboard noisereduce   (using always-listening mode for now)")
    if not ptt:
        SILENCE_RMS = calibrate_mic()
    _init_mics()
    wait_for_ollama()
    try:
        think("hello")  # warm up the model
    except Exception as e:
        print(f"(warm-up failed, continuing: {type(e).__name__}: {e})")
    greeting = "Systems online. At your service, sir."
    if ptt:
        if _is_copilot(PTT_KEY):
            greeting += " Hold the Copilot key while you speak, or tap it to start and stop."
        else:
            greeting += f" Hold {PTT_KEY} while you speak."
    speak(greeting)
    if ANNOUNCE_DEVICES:
        try:
            import jarvis_devices
            jarvis_devices.start(speak=lambda t: speak(t), on_audio_change=_mic_dirty.set)
        except ImportError:
            print("(jarvis_devices.py not found -- device announcements are off)")
    active_until = 0
    while True:
        text = listen()
        if not text:
            continue
        print("YOU:" if _lang == "en" else "YOU (Tamil -> English):", text)
        if ptt:
            # push-to-talk: every utterance is a command, wake word optional
            if has_wake(text):
                text = strip_wake(text) or "hello"
        elif has_wake(text):
            active_until = time.time() + ACTIVE_WINDOW
            text = strip_wake(text) or "hello"
        elif time.time() > active_until:
            continue
        else:
            active_until = time.time() + ACTIVE_WINDOW
        if any(w in text.lower() for w in ("shutdown", "goodbye", "power down")):
            speak("Powering down. Goodbye, sir.")
            break
        try:
            if _run_fast_command(text):
                continue
            speak(think(text))
        except Exception as e:                 # one bad answer must never kill Jarvis
            print(f"(something went wrong: {type(e).__name__}: {e})")
            speak("Sorry sir, something went wrong with that one.")


if __name__ == "__main__":
    main()
