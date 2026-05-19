import time
import sys
import ctypes
import threading
from . import config


class TextInjector:
    """
    Text injection engine for Bolo voice-to-text.

    Handles injecting transcribed text into the target application window.

    Responsibilities:
        - Focus restoration to target window
        - Strategy selection (paste vs direct typing)
        - Clipboard manipulation for paste strategy
        - Text injection via Ctrl+V or keyboard.write()

    Injection Strategies:
        1. Paste Hack: For long text (>15 chars) or text with newlines/unicode
           - Copies text to clipboard, pastes via Ctrl+V, restores clipboard
        2. Direct Type: For short ASCII text
           - Uses keyboard.write() for reliability

    Race Condition Fix (Phase 1):
        - Original clipboard captured BEFORE modification (synchronous)
        - Clipboard restored SYNCHRONOUSLY (not with delay)
        - Duplicate detection: only restore if we own the clipboard

    Thread Safety:
        - All methods are static (no shared state)
        - pyperclip operations are atomic
    """

    @staticmethod
    def _restore_focus(hwnd):
        """Forcefully restores focus to the target window."""
        if not hwnd:
            return
        try:
            # If window is minimized, restore it
            SW_RESTORE = 9
            if ctypes.windll.user32.IsIconic(hwnd):
                ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
                time.sleep(0.05)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.06)
        except Exception as e:
            print(f"Focus restore error: {e}")

    @staticmethod
    def inject(text, target_hwnd=None):
        """
        Hybrid Injection Engine:
        1. Paste Hack: for long text/paragraphs (fastest, preserves formatting)
        2. Direct Type: for short text (most reliable across all apps)
        """
        if not text: return

        # 1. Focus Verification & Settling Delay
        time.sleep(0.12) # Settling delay after hotkey release
        if target_hwnd:
            TextInjector._restore_focus(target_hwnd)

        # 2. Strategy Selection
        # If text is very short (<15 chars), typing is safer and less intrusive
        use_paste = len(text) > 15 or "\n" in text or any(ord(c) > 127 for c in text)

        try:
            import pyperclip
            import keyboard
            
            if use_paste:
                # PASTE STRATEGY - SYNCHRONOUS BACKUP WITH DUPLICATE DETECTION
                # CRITICAL: Capture original clipboard BEFORE ANY modification
                try:
                    orig_clipboard = pyperclip.paste()
                except:
                    orig_clipboard = None  # If paste fails, don't restore

                # Modify clipboard and inject
                pyperclip.copy(text)
                time.sleep(0.05) # Let OS register clipboard change
                keyboard.press_and_release('ctrl+v')
                time.sleep(0.2) # Let paste operation complete

                # Check if clipboard content matches what we injected
                # If user already copied something else, skip restoration
                try:
                    current_clipboard = pyperclip.paste()
                    clipboard_changed_by_us = (current_clipboard == text)
                except:
                    current_clipboard = None
                    clipboard_changed_by_us = True

                # Synchronous restoration - only if we own the clipboard
                if orig_clipboard is not None and clipboard_changed_by_us:
                    try:
                        pyperclip.copy(orig_clipboard)
                        print(f"[Injector] Clipboard restored (length: {len(orig_clipboard)})")
                    except Exception as e:
                        print(f"[Injector] Warning: Failed to restore clipboard: {e}")
                elif orig_clipboard is None:
                    print("[Injector] Skipped clipboard restoration (original not captured)")
                else:
                    print("[Injector] Skipped clipboard restoration (user changed clipboard)")
            else:
                # DIRECT TYPE STRATEGY
                keyboard.write(text, delay=0.01)

        except Exception as e:
            print(f"[Injector] Error: {e}. Falling back to raw typing.")
            try:
                import keyboard
                keyboard.write(text, delay=0.02)
            except:
                pass

    @staticmethod
    def play_beep(frequency, duration):
        if sys.platform != "win32":
            return
        try:
            import winsound
            winsound.Beep(frequency, duration)
        except Exception:
            pass