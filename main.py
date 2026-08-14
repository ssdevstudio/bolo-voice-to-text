import sys
import os
import threading
import time
import traceback
import atexit
import argparse
import logging
from typing import Any, Callable, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from src import config
from src.audio_engine import AudioEngine
from src.injector import TextInjector
from src.hotkey_monitor import HotkeyMonitor
from src.tray_icon import TrayIcon
from src.gui import start_gui
from src.utils import setup_logging, purge_old_history
from src.onboarding import maybe_show as maybe_show_onboarding

# ─── Structured Logging Setup ───────────────────────────────────────────────
_logger: Optional[logging.Logger] = None  # Set in __main__ after config is loaded

# ─── Single Instance Lock ───────────────────────────────────────────────────
global_args: Optional[argparse.Namespace] = None  # CLI arguments, set in __main__
_LOCK_FILE = config._get_lock_path()  # APPDATA when frozen, project root in dev

def _cleanup_temp_files() -> None:
    """Clean up temporary files on exit."""
    if os.path.exists(_LOCK_FILE):
        try:
            os.remove(_LOCK_FILE)
            print(f"[Cleanup] Removed {_LOCK_FILE}")
        except Exception as e:
            print(f"[Cleanup] Could not remove {_LOCK_FILE}: {e}")

# Register cleanup handler
atexit.register(_cleanup_temp_files)

def _kill_existing_instances() -> None:
    """Kill prior Bolo instance via lock-file PID.

    Lock file is created in user data dir and stores the PID of the running
    instance. We trust the PID — no process-name scanning, which can match
    unrelated programs and is racy.
    """
    import psutil
    current_pid = os.getpid()

    if not os.path.exists(_LOCK_FILE):
        return
    try:
        with open(_LOCK_FILE, "r") as f:
            old_pid = int(f.read().strip())
    except Exception as e:
        print(f"[SingleInstance] Lock file read error: {e}")
        try:
            os.remove(_LOCK_FILE)
        except Exception:
            pass
        return

    if old_pid == current_pid:
        return

    try:
        proc = psutil.Process(old_pid)
        # Verify it's actually a Bolo process before killing — prevents
        # accidentally terminating an unrelated PID we don't own.
        cmdline = " ".join(proc.cmdline())
        if "Bolo" not in cmdline and "bolo" not in cmdline.lower():
            print(f"[SingleInstance] Stale lock (PID {old_pid} is not Bolo). Removing.")
        else:
            print(f"[SingleInstance] Stopping prior instance PID {old_pid}...")
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except psutil.TimeoutExpired:
                proc.kill()
            time.sleep(0.3)
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied:
        print(f"[SingleInstance] Cannot terminate PID {old_pid}: access denied.")
    finally:
        try:
            os.remove(_LOCK_FILE)
        except Exception:
            pass

def _write_lock() -> None:
    """Write current PID to lock file."""
    with open(_LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))

def _remove_lock() -> None:
    """Remove lock file on exit."""
    try:
        if os.path.exists(_LOCK_FILE):
            os.remove(_LOCK_FILE)
    except Exception:
        pass
# ────────────────────────────────────────────────────────────────────────────


class BoloApp:
    def __init__(self) -> None:
        self.current_language = config.DEFAULT_LANGUAGE
        self.audio_engine = AudioEngine()
        self.injector = TextInjector()
        self.gui = start_gui(self.on_settings_change, self.quit_app)
        # Handle --minimized flag (set by Bolo.lnk for startup)
        args = global_args  # Set by argparse in __main__
        if args.minimized:
            self.gui.withdraw()
            print("[Main] Starting minimized to system tray")
        self.tray = TrayIcon(self.quit_app, self.set_language)
        self.tray.volume_provider = self.audio_engine
        self.tray.on_show_gui = self.gui.show_window
        self.tray.on_reconnect = self.audio_engine.reconnect_mic
        # Pass target_hwnd to stop_recording
        self.monitor = HotkeyMonitor(self.start_recording, self.stop_recording)
        self._quitting = False
        self._pending_hwnd = None
        self._processing_thread: threading.Thread | None = None

    def on_settings_change(self, key: str, value: Any) -> None:
        if key == 'language':
            self.set_language(value)
        elif key == 'hotkey':
            self.monitor.update_key(value)
        elif key == 'longpress':
            self.monitor.threshold = float(value)
            print(f"Long-press threshold: {int(value * 1000)}ms")
        elif key == 'engine':
            print(f"Engine changed to: {value}")
            # Invalidate cached models so they reload fresh on next transcription
            # with the new engine. Zero-STT is only relevant for Whisper engine,
            # so invalidate it unconditionally (it's lazy-loaded and cheap to skip).
            self.audio_engine.reload_whisper_model()
            self.audio_engine.reload_zero_stt_model()
        elif key == 'model':
            print(f"Model changed to: {value}")
            self.audio_engine.reload_whisper_model()
        elif key == 'download_model':
            def _do_download():
                result = self.audio_engine.download_model_now(progress_cb=self.gui.on_download_progress)
                self._schedule_gui(lambda r=result: self._on_download_complete(r))
            threading.Thread(target=_do_download, daemon=True).start()
        elif key == 'download_zero_stt':
            def _do_zero():
                result = self.audio_engine.download_zero_stt_now(progress_cb=self.gui.on_zero_stt_progress)
                self._schedule_gui(lambda r=result: self.gui.on_zero_stt_complete(r))
            threading.Thread(target=_do_zero, daemon=True).start()
        elif key == 'auto_energy':
            self.audio_engine.recognizer.dynamic_energy_threshold = value
        elif key == 'pre_roll':
            import collections
            self.audio_engine.pre_roll_buffer = collections.deque(
                maxlen=int(self.audio_engine.rate / self.audio_engine.chunk_size * value)
            )

    def _on_download_complete(self, success: bool) -> None:
        """Called from GUI thread when download completes."""
        if hasattr(self.gui, '_is_downloading'):
            self.gui._is_downloading = False
        self.gui.refresh_download_button()
        if success:
            self.gui.status_lbl.configure(text="Model downloaded successfully!", text_color=config.SUCCESS_COLOR)
            self.gui.after(3000, lambda: self.gui.status_lbl.configure(text="Ready to transcribe", text_color=config.TEXT_PRIMARY))
        else:
            self.gui.status_lbl.configure(text="Model download failed", text_color=config.ERROR_COLOR)
            self.gui.after(3000, lambda: self.gui.status_lbl.configure(text="Ready to transcribe", text_color=config.TEXT_PRIMARY))

    def set_language(self, lang_code: str) -> None:
        print(f"Language changed to: {lang_code}")
        self.current_language = lang_code
        self.gui.update_ui_language(lang_code)
        self.tray.update_language_state(lang_code)

    def start_recording(self, target_hwnd: Optional[int] = None) -> None:
        if self.audio_engine.is_recording:
            return
        # Capture target HWND once at KEY_DOWN (most accurate moment)
        hwnd = target_hwnd
        if not hwnd:
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetForegroundWindow()
            except Exception:
                pass
        print(f"Target window: {hwnd}")
        print("Recording started...")
        self.audio_engine.start_recording()
        if config.BEEP_ON_START:
            threading.Thread(target=self.injector.play_beep, args=(1000, 100), daemon=True).start()
        self._schedule_gui(lambda: self.gui.set_listening_state("listening"))
        self._schedule_gui(lambda: self.tray.show_status("Listening...", "#e74c3c"))
        self._schedule_gui(lambda: self.tray.set_icon_state(recording=True))
        # Store hwnd for _process_and_inject thread (captured once, no race)
        self._pending_hwnd = hwnd

    def stop_recording(self, target_hwnd: Optional[int] = None) -> None:
        if not self.audio_engine.is_recording:
            return
        hwnd = self._pending_hwnd
        self._pending_hwnd = None
        print(f"Recording stopped. Processing for window {hwnd}...")
        self._schedule_gui(lambda: self.gui.set_listening_state("processing"))
        self._schedule_gui(lambda: self.tray.hide_status())
        self._schedule_gui(lambda: self.tray.set_icon_state(recording=False))
        t = threading.Thread(target=self._process_and_inject, args=(hwnd,))
        t.daemon = True
        self._processing_thread = t
        t.start()

    def _process_and_inject(self, hwnd: Optional[int]) -> None:
        try:
            text = self.audio_engine.stop_recording(language=self.current_language)
            self._schedule_gui(lambda: self.gui.set_listening_state("idle"))
            if text:
                print(f"Transcription: {text}")
                self.injector.inject(text, target_hwnd=hwnd)
                if config.BEEP_ON_END:
                    self.injector.play_beep(1200, 100)
            else:
                self._schedule_gui(lambda: self.tray.set_icon_state(recording=False))
        except Exception as e:
            # CRITICAL: Log full traceback for debugging
            print(f"[ERROR] Processing error: {e}")
            traceback.print_exc()
            self._schedule_gui(lambda: self.gui.set_listening_state("idle"))
            self._schedule_gui(lambda: self.tray.set_icon_state(recording=False))

    def _schedule_gui(self, callback: Callable[[], None]) -> None:
        """Thread-safe GUI callback scheduler with error handling."""
        try:
            # Only schedule the callback if GUI is still active
            if self.gui and hasattr(self.gui, 'winfo_exists') and self.gui.winfo_exists():
                # Wrap callback to catch exceptions in the callback itself
                def safe_callback():
                    try:
                        callback()
                    except Exception as e:
                        print(f"[GUI] Callback error: {e}")
                        traceback.print_exc()
                self.gui.after(0, safe_callback)
            else:
                print("[GUI] Warning: GUI not available for callback")
        except Exception as e:
            print(f"[GUI] Error scheduling callback: {e}")

    def run(self) -> None:
        print(f"{config.APP_NAME} starting...")
        self.monitor.start()
        tray_t = threading.Thread(target=self.tray.run, daemon=True)
        tray_t.start()
        # First-launch onboarding wizard (skipped on subsequent runs)
        try:
            self.gui.after(300, lambda: maybe_show_onboarding(self.gui, self.audio_engine))
        except Exception as e:
            print(f"[Main] Onboarding launch failed: {e}")
        # Background prewarm: silently load local model so first transcription is instant
        try:
            self.gui.after(1000, self._prewarm_model)
        except Exception as e:
            print(f"[Main] Prewarm schedule failed: {e}")
        # Periodic audio-engine health check — restarts the bg listener if it
        # died silently (e.g. device unplugged). check_health() was defined
        # but never wired in; without this, a dead listener leaves recordings
        # silent with no auto-recovery.
        try:
            self.gui.after(10000, self._health_tick)
        except Exception as e:
            print(f"[Main] Health tick schedule failed: {e}")
        try:
            self.gui.mainloop()
        except KeyboardInterrupt:
            print("Interrupted by user.")
        finally:
            if not self._quitting:
                self.quit_app()

    def quit_app(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        print(f"{config.APP_NAME} shutting down...")
        try:
            self.monitor.stop()
        except Exception as e:
            print(f"Monitor shutdown error: {e}")
        try:
            # Signal audio engine to stop background listener and kill stream
            self.audio_engine._stop_engine_event.set()  # Signal bg listener to stop

            # Wait for background listener thread to finish (with timeout)
            if self.audio_engine._bg_listener_thread and self.audio_engine._bg_listener_thread.is_alive():
                self.audio_engine._bg_listener_thread.join(timeout=2.0)
                if self.audio_engine._bg_listener_thread.is_alive():
                    print("[Audio] Background listener thread did not stop gracefully")

            # Now kill the stream
            self.audio_engine.kill_stream()
        except Exception as e:
            print(f"Audio shutdown error: {e}")
        try:
            if self.tray.icon:
                self.tray.icon.stop()
        except Exception as e:
            print(f"Tray shutdown error: {e}")
        try:
            self.gui.after(0, self.gui.quit)
        except Exception as e:
            print(f"GUI shutdown error: {e}")
        # Wait for any in-flight transcription/injection thread to finish
        # so it doesn't access freed resources during shutdown.
        if self._processing_thread and self._processing_thread.is_alive():
            self._processing_thread.join(timeout=5.0)
            if self._processing_thread.is_alive():
                print("[Main] Transcription thread still alive after 5s shutdown timeout")
        sys.exit(0)

    def show_window(self) -> None:
        self.gui.show_window()

    def _prewarm_model(self) -> None:
        """Prewarm local model in background (downloaded models only)."""
        import threading
        def _warm():
            if self._quitting:
                return
            engine = config.TRANSCRIPTION_ENGINE
            is_hinglish = self.current_language == 'xx-HI'

            if engine != 'whisper' and engine != 'google':
                return

            # For Hinglish: prewarm Zero-STT if available, otherwise Whisper fallback
            if is_hinglish:
                if engine == 'whisper':
                    from src.audio_engine import is_zero_stt_downloaded, is_whisper_model_downloaded
                    if is_zero_stt_downloaded():
                        print("[Prewarm] Background: load zero-stt...")
                        self.audio_engine._get_zero_stt_model()
                    elif is_whisper_model_downloaded(config.WHISPER_MODEL):
                        print("[Prewarm] Background: load Whisper...")
                        self.audio_engine._get_whisper_model()
                    else:
                        print("[Prewarm] No local model found, skipping.")
                        return
                    print("[Prewarm] Model ready.")
            elif engine == 'whisper':
                from src.audio_engine import is_whisper_model_downloaded
                if is_whisper_model_downloaded(config.WHISPER_MODEL):
                    print("[Prewarm] Background: load Whisper...")
                    self.audio_engine._get_whisper_model()
                else:
                    print("[Prewarm] No local Whisper model, skipping.")

        threading.Thread(target=_warm, daemon=True).start()

    def _health_tick(self) -> None:
        """Periodic audio-engine liveness check, self-rescheduling every 10s.

        Restarts the background listener if it died silently. Stops rescheduling
        once the app is quitting.
        """
        if self._quitting:
            return
        try:
            self.audio_engine.check_health()
        except Exception as e:
            print(f"[Main] Health tick error: {e}")
        # Reschedule only while still running (self.gui.after would otherwise
        # keep a dangling timer after the window is destroyed).
        if not self._quitting:
            try:
                self.gui.after(10000, self._health_tick)
            except Exception:
                pass


if __name__ == "__main__":
    # ─── CLI Argument Parsing ──────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        prog="Bolo",
        description="Voice-to-text desktop application with hotkey activation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                Start Bolo normally
  python main.py --minimized    Start minimized to system tray
  python main.py --help         Show this help message
        """
    )
    parser.add_argument(
        "--minimized", "-m",
        action="store_true",
        help="Start minimized to system tray (useful for auto-startup)"
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"%(prog)s {config.VERSION}"
    )
    global_args = parser.parse_args()

    # ─── Initialize Structured Logging ─────────────────────────────────────
    _logger = setup_logging(config.APP_NAME)
    _logger.info(f"{config.APP_NAME} v{config.VERSION} starting...")

    _kill_existing_instances()  # Purana band karo
    _write_lock()               # Apna PID likho
    # Trim history entries older than 7 days (function existed but was never
    # wired in at startup — history.json grew unbounded despite MAX_HISTORY
    # only capping per-session appends).
    try:
        purge_old_history()
    except Exception as e:
        _logger.warning(f"History purge skipped: {e}")
    try:
        app = BoloApp()
        app.run()
    except Exception as e:
        _logger.critical(f"Unexpected crash: {e}", exc_info=True)
    finally:
        _remove_lock()          # Exit pe lock hataao
        _logger.info(f"{config.APP_NAME} shutdown complete")
