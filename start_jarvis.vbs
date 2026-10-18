' Starts Jarvis (HUD Pro) silently when you log in to Windows.
' Copy this file into the Startup folder (Win+R -> shell:startup). Edit the two lines marked CHANGE if needed.
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = "C:\jarvis"                       ' CHANGE: the folder that holds jarvis.py
script = "jarvis_hud_pro.py"               ' CHANGE: jarvis_hud.py = Iron Man HUD, jarvis_apps.py = no HUD

' 1) proof that Windows really ran this file (open startup_check.txt after you log in)
On Error Resume Next
Set f = fso.OpenTextFile(folder & "\startup_check.txt", 8, True)
f.WriteLine Now & "  start_jarvis.vbs started"
f.Close
On Error GoTo 0

' 2) give Windows time to finish starting (network, audio, Ollama)
WScript.Sleep 30000

' 3) start Jarvis, hidden. Everything it prints goes to jarvis_log.txt (-u = write it immediately)
sh.CurrentDirectory = folder
sh.Run "cmd /c py -3.12 -u " & script & " > jarvis_log.txt 2>&1", 0, False
