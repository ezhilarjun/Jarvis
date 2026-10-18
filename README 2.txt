JARVIS v2  (Ollama brain + voice wake-up + HUD + app/desktop/phone control)
===========================================================================

1) Copy ALL these files into C:\jarvis (replace the old ones).
   Rename ".env.example" to ".env" and set JARVIS_INPUT_DEVICE (0 worked for you).

2) Ollama must be running with your model:
     ollama list            (shows your models)
     ollama pull llama3.2:3b   (if you don't have it)
   If you use another model, set OLLAMA_MODEL in .env.

3) Install libraries (use Python 3.12, NOT 3.14 -- faster-whisper needs it):
     py -3.12 -m pip install -r requirements.txt

4) Run:
     py -3.12 jarvis_hud.py

   Wait for "Systems online". Then say:
     "Jarvis, wake up"            -> greets you + opens Cursor (edit jarvis_welcome.py)
     "Jarvis, what time is it?"   -> answers
     "Jarvis, open notepad"       -> opens apps
     "Jarvis, search Google for ..." / "play ... on YouTube"
     "Jarvis, shutdown"           -> stops Jarvis

Files:
  jarvis_hud.py      main entry (ring HUD). Right-click ring = quit.
  jarvis.py          core: mic -> Whisper -> Ollama -> voice
  jarvis_welcome.py  "wake up" routine (what to open)
  jarvis_apps.py     any installed app, WhatsApp Web, Gmail, Spotify
  jarvis_desktop.py  mouse/keyboard/windows/files/shell/screen
  jarvis_phone.py    Android control via ADB
  test_mic.py        mic level test
  start_jarvis.vbs   optional auto-start on boot

GPU (optional, NVIDIA only)
---------------------------
"Speech model running on CPU" is normal and works fine. To try the GPU:
  1. Run:  nvidia-smi        (if this fails, you have no NVIDIA GPU -- stay on CPU)
  2. Run:  py -3.12 -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
  3. In .env set:  JARVIS_WHISPER_DEVICE=cuda
If the GPU can't start, Jarvis prints why and uses the CPU automatically.

AUTO-START AT LOGIN
-------------------
In C:\jarvis run ONCE:
    py -3.12 install_autostart.py
Jarvis then starts ~20 seconds after you sign in to Windows (errors go to jarvis_log.txt).
    py -3.12 install_autostart.py status    -> check it is installed
    py -3.12 install_autostart.py remove    -> uninstall
Notes: it starts when you SIGN IN, not when waking from sleep (Jarvis keeps running
through sleep; if the mic stops after sleep, restart it). Only keep one auto-start copy:
delete any old start_jarvis.vbs from Win+R -> shell:startup.
