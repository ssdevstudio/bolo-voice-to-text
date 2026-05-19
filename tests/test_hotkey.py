"""
Test script to debug keyboard hotkey detection.
Run this script and press keys to see what names the keyboard library detects.
"""
import keyboard
import time

print("=" * 50)
print("Bolo Hotkey Debug Test")
print("=" * 50)
print("Press any key to see its name.")
print("Press ESC to exit.")
print()

detected_keys = set()

def on_event(event):
    key_name = event.name if event.name else ""
    if key_name:
        detected_keys.add(key_name)
        print(f"  {event.event_type:10} : '{key_name}'")

keyboard.on_press(lambda e: on_event(e))
keyboard.on_release(lambda e: on_event(e))

print("Listening for keys...")
print()

try:
    while True:
        time.sleep(0.1)
except KeyboardInterrupt:
    pass
except:
    pass

print()
print("Keys detected during session:")
for key in sorted(detected_keys):
    print(f"  - {key}")
