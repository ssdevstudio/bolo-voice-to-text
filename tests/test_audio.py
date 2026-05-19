"""
Standalone Audio Engine Test
Usage: python tests/test_audio.py
"""
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from src.audio_engine import AudioEngine

print("=" * 50)
print("Bolo Audio Engine Standalone Test")
print("=" * 50)

engine = AudioEngine()

print("\nTest 1: Short recording (3 seconds)")
print("Speak something now...")
engine.start_recording()
time.sleep(3)
text = engine.stop_recording(language="en-IN")
print(f"\nTranscription: {text if text else '(no text)'}")

time.sleep(1)

print("\nTest 2: Second recording (3 seconds) - checking re-init")
print("Speak something again...")
engine.start_recording()
time.sleep(3)
text = engine.stop_recording(language="en-IN")
print(f"\nTranscription: {text if text else '(no text)'}")

engine.kill_stream()
print("\nTest complete.")