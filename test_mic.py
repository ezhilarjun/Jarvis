"""Quick mic level test. Run this and speak -- watch the numbers.
Silence should show near 0.000-0.002. Speaking should spike well above that.
Press Ctrl+C to stop.
"""
import numpy as np
import sounddevice as sd

SR = 16000

print("Speak now, watch the RMS numbers (Ctrl+C to stop)...")
with sd.InputStream(samplerate=SR, channels=1, dtype="float32") as stream:
    while True:
        data, _ = stream.read(1600)  # 0.1s chunks
        rms = float(np.sqrt(np.mean(data ** 2)))
        bar = "#" * int(rms * 500)
        print(f"RMS: {rms:.4f} {bar}")
