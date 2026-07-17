import logging
import logging.handlers
import os
import sys


class _StreamToLogger:
    """File-like proxy that mirrors writes to a logger.

    Used to capture legacy print() output into the rotating log file without
    rewriting every print() call. When the original stream is None (e.g.
    PyInstaller --windowed mode where stdout/stderr are detached), writes
    only go to the logger.
    """
    def __init__(self, original_stream, logger, level):
        self._original = original_stream
        self._logger = logger
        self._level = level
        self._buffer = ""

    def write(self, message):
        if not message:
            return
        # Mirror to original stream if attached (console / IDE redirection)
        if self._original is not None:
            try:
                self._original.write(message)
            except Exception:
                pass
        self._buffer += message
        # Flush complete lines to the logger
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip()
            if line:
                try:
                    self._logger.log(self._level, line)
                except Exception:
                    pass

    def flush(self):
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass

    def isatty(self):
        if self._original is None:
            return False
        try:
            return self._original.isatty()
        except Exception:
            return False

    def fileno(self):
        if self._original is None:
            raise OSError("no fileno (stream is detached)")
        return self._original.fileno()


def setup_logging(app_name="Bolo", log_dir=None, max_bytes=10 * 1024 * 1024, backup_count=3):
    """Rotating file + console logging. Also mirrors stdout/stderr to the
    log file so legacy `print()` calls land in the same place.

    log_dir defaults to %APPDATA%/Bolo/logs on Windows, ~/.config/bolo/logs
    on Linux, ~/Library/Logs/Bolo on macOS.
    """
    import pathlib

    if log_dir is None:
        if sys.platform == "win32":
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
            log_dir = os.path.join(base, "Bolo", "logs")
        elif sys.platform == "darwin":
            log_dir = os.path.join(os.path.expanduser("~"), "Library", "Logs", "Bolo")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
            log_dir = os.path.join(base, "bolo", "logs")

    pathlib.Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = os.path.join(log_dir, f"{app_name}.log")

    logger = logging.getLogger(app_name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # File handler only — console output comes from the original stdout that
    # _StreamToLogger preserves. Adding a console StreamHandler would cause
    # every print() to appear twice (raw + "[INFO] raw").
    logger.addHandler(file_handler)
    logger.propagate = False

    # Mirror stdout/stderr -> log file (so all print() output is persisted),
    # but the underlying stdout still writes to the console as usual.
    sys.stdout = _StreamToLogger(sys.stdout, logger, logging.INFO)
    sys.stderr = _StreamToLogger(sys.stderr, logger, logging.ERROR)

    logger.info(f"Logging initialized. Log file: {log_file}")
    return logger


def get_logger(name=None):
    """Get a child logger for a specific component."""
    from . import config
    parent = logging.getLogger(config.APP_NAME)
    return parent.getChild(name) if name else parent

def get_startup_key():
    if sys.platform != "win32":
        return None
    try:
        import winreg
        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
    except Exception as e:
        print(f"Error opening startup registry key: {e}")
        return None

def set_run_on_startup(app_name, enable=True):
    if sys.platform != "win32":
        return False
    import winreg
    key = get_startup_key()
    if not key:
        return False
    try:
        if enable:
            exe_path = os.path.abspath(sys.argv[0])
            if exe_path.endswith('.py') or exe_path.endswith('.pyc'):
                value = f'"{sys.executable}" "{exe_path}" --minimized'
            else:
                value = f'"{exe_path}" --minimized'
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, value)
        else:
            try:
                winreg.DeleteValue(key, app_name)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Error setting startup registry: {e}")
        return False


def is_run_on_startup(app_name):
    if sys.platform != "win32":
        return False
    import winreg
    key = get_startup_key()
    if not key:
        return False
    try:
        winreg.QueryValueEx(key, app_name)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        if key: winreg.CloseKey(key)
        return False
    except Exception:
        if key: winreg.CloseKey(key)
        return False

def purge_old_history(days=7):
    """Deletes history entries older than `days` days. Called at startup."""
    from datetime import datetime, timedelta

    from . import config

    history_path = config._get_history_path()
    history = config.atomic_json_read(history_path, default=[])
    if not isinstance(history, list) or not history:
        return

    cutoff = datetime.now() - timedelta(days=days)
    kept = []
    for entry in history:
        ts = entry.get("time", "")
        try:
            if datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") > cutoff:
                kept.append(entry)
        except ValueError:
            kept.append(entry)  # Keep malformed timestamps rather than discard

    if len(kept) != len(history):
        config.atomic_json_write(history_path, kept)
        print(f"[History] Purged {len(history) - len(kept)} entries older than {days} days.")
