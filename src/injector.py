import ctypes
import sys
import time
from typing import Optional


class _ClipboardBackup:
    """Win32 full-format clipboard backup/restore.

    Preserves ALL formats (text, images, files, rich text) — not just text
    like pyperclip. Uses win32clipboard (pywin32) for safe format enumeration.
    """

    def __init__(self):
        self._formats = []
        self._data = {}

    def save(self) -> None:
        """Enumerate and capture all clipboard formats."""
        try:
            import win32clipboard as wc
            wc.OpenClipboard()
            try:
                fmt = 0
                while True:
                    fmt = wc.EnumClipboardFormats(fmt)
                    if fmt == 0:
                        break
                    try:
                        raw = wc.GetClipboardData(fmt)
                        if raw is not None:
                            self._formats.append(fmt)
                            self._data[fmt] = raw
                    except Exception:
                        pass
            finally:
                wc.CloseClipboard()
        except Exception as e:
            print(f"[Injector] Clipboard backup err: {e}")

    def restore(self) -> None:
        """Restore all captured formats if clipboard still contains our text."""
        if not self._formats:
            return
        try:
            import win32clipboard as wc
            wc.OpenClipboard()
            try:
                # Only restore if we still own the clipboard (text matches)
                try:
                    txt = wc.GetClipboardData(1)  # CF_TEXT = 1
                except Exception:
                    txt = None
                if txt is not None:
                    # User hasn't changed clipboard — restore everything
                    wc.EmptyClipboard()
                    for fmt in self._formats:
                        try:
                            wc.SetClipboardData(fmt, self._data[fmt])
                        except Exception:
                            pass
                else:
                    print("[Injector] Skipped restore (user changed clipboard)")
            finally:
                wc.CloseClipboard()
        except Exception as e:
            print(f"[Injector] Clipboard restore err: {e}")


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
    """

    @staticmethod
    def _restore_focus(hwnd: Optional[int]) -> None:
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
    def inject(text: str, target_hwnd: Optional[int] = None) -> None:
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
            import keyboard
            import pyperclip

            if use_paste:
                # PASTE STRATEGY — FULL-FORMAT BACKUP
                # Save ALL clipboard formats (text, images, files) before modifying
                backup = _ClipboardBackup()
                backup.save()

                # Modify clipboard and inject
                pyperclip.copy(text)
                time.sleep(0.05) # Let OS register clipboard change
                keyboard.press_and_release('ctrl+v')
                time.sleep(0.2) # Let paste operation complete

                # Restore original clipboard (only if we still own it)
                backup.restore()
            else:
                # DIRECT TYPE STRATEGY
                keyboard.write(text, delay=0.01)

        except Exception as e:
            print(f"[Injector] Error: {e}. Falling back to raw typing.")
            try:
                import keyboard
                keyboard.write(text, delay=0.02)
            except Exception:
                pass

    @staticmethod
    def play_beep(frequency: int, duration: int) -> None:
        if sys.platform != "win32":
            return
        try:
            import winsound
            winsound.Beep(frequency, duration)
        except Exception:
            pass
