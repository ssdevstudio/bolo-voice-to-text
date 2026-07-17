import keyboard
import time
import threading
from . import config


class HotkeyMonitor:
    """
    Hotkey monitor for Bolo voice-to-text activation.

    Monitors keyboard events and triggers callbacks when the activation key
    is held for LONG_PRESS_THRESHOLD seconds (default: 0.15s).

    Responsibilities:
        - Keyboard hook via python-keyboard library
        - Long-press detection (vs tap/short-press)
        - Target window HWND capture for correct text injection
        - Hotkey validation against whitelist

    Thread Safety:
        - Uses threading.Lock for state protection
        - Keyboard events handled in separate callback thread

    Race Condition Fix (Phase 1):
        - HWND captured immediately on KEY_DOWN (not on timer callback)
        - HWND passed to callbacks for accurate text injection
    """
    def __init__(self, on_hold_start, on_hold_end):
        self.on_hold_start = on_hold_start
        self.on_hold_end = on_hold_end
        self.is_held = False
        self.press_time = 0
        self.activation_key = config.ACTIVATION_KEY
        self.threshold = config.LONG_PRESS_THRESHOLD
        self._lock = threading.Lock()
        self._already_triggered = False
        self._timer = None
        self._hook_id = None
        self._target_hwnd = None

    def start(self):
        self._hook_id = keyboard.hook(self._on_event)

    def update_key(self, new_key):
        # CRITICAL: Validate hotkey before accepting it
        if not new_key or new_key.lower() not in config.VALID_HOTKEYS:
            print(f"[Hotkey] Error: Invalid hotkey '{new_key}'")
            return False

        with self._lock:
            print(f"[Hotkey] Updating hotkey from '{self.activation_key}' to: {new_key}")
            self.activation_key = new_key
            self.is_held = False
            self._already_triggered = False
            if self._timer:
                try:
                    self._timer.cancel()
                except Exception:
                    pass
                self._timer = None
        return True

    def _is_match(self, key_name):
        """Match a key event against the configured activation key.

        Windows quirk: on many keyboard layouts (Indian InScript, EU layouts
        with AltGr), pressing the physical Right Alt key emits an 'alt gr'
        event, not 'right alt'. So 'right alt' must accept both. Users who
        rely on AltGr to type @/€ etc. should pick a different hotkey
        (Left Alt, F1-F12, etc.) instead.
        """
        if not key_name:
            return False
        target = self.activation_key.lower()
        key = key_name.lower()
        if target == "right alt":
            return key in ("right alt", "alt gr")
        if target == "alt gr":
            return key == "alt gr"
        return key == target

    def _get_active_window(self):
        """Native Win32 call to get current focus."""
        import ctypes
        try:
            return ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return None

    def _on_event(self, event):
        with self._lock:
            key_name = event.name if event.name else ""

            # DEBUG: Log all key events to see what's being detected
            # print(f"[Hotkey] Event: {event.event_type} - '{key_name}' (target: '{self.activation_key}')")

            if not self._is_match(key_name):
                return

            print(f"[Hotkey] Matched! {event.event_type} - '{key_name}'")

            if event.event_type == keyboard.KEY_DOWN:
                if not self.is_held:
                    self.is_held = True
                    self.press_time = time.time()
                    self._target_hwnd = self._get_active_window() # Capture focus immediately
                    self._already_triggered = False
                    
                    if self._timer: self._timer.cancel()
                    self._timer = threading.Timer(self.threshold, self._on_long_press)
                    self._timer.daemon = True
                    self._timer.start()
            elif event.event_type == keyboard.KEY_UP:
                self.is_held = False
                if self._timer:
                    self._timer.cancel()
                    self._timer = None
                
                if self._already_triggered:
                    self._already_triggered = False
                    self.on_hold_end(self._target_hwnd) # Pass target window back

    def _on_long_press(self):
        with self._lock:
            if self.is_held and not self._already_triggered:
                self._already_triggered = True
                self.on_hold_start(self._target_hwnd)  # Pass HWND captured at KEY_DOWN

    def stop(self):
        try:
            if self._hook_id is not None:
                keyboard.unhook(self._hook_id)
                self._hook_id = None
        except Exception:
            pass