import json
import os
import sys
import tempfile
import threading
from typing import Any, Optional

# Per-path in-process lock for atomic JSON IO. Single-instance enforcement
# makes cross-process locking unnecessary.
_FILE_LOCKS: dict[str, threading.RLock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def _lock_for(path: str) -> threading.RLock:
    """Return the RLock for this path (reentrant so read+write nesting works)."""
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _FILE_LOCKS[path] = lock
        return lock


def atomic_json_read(path: str, default: Optional[Any] = None) -> Any:
    """Read a JSON file under per-path lock. Returns default if file missing/invalid."""
    with _lock_for(path):
        if not os.path.exists(path):
            return default
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return default
            return json.loads(content)
        except Exception as e:
            print(f"[IO] Read failed for {path}: {e}")
            return default


def atomic_json_write(path: str, data: Any) -> bool:
    """Write JSON atomically (tmp file + rename) under per-path lock.

    Atomic on the same filesystem — rename() is the standard durability trick.
    Prevents partial writes from corrupting state on crash mid-write.
    """
    with _lock_for(path):
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(tmp, path)
            return True
        except Exception as e:
            print(f"[IO] Write failed for {path}: {e}")
            try:
                os.remove(tmp)
            except Exception:
                pass
            return False

# Application Settings
APP_NAME = "Bolo"
VERSION = "1.2.0"

# --- DEFAULTS ---
_DEFAULTS = {
    "ACTIVATION_KEY": 'right alt',
    "LONG_PRESS_THRESHOLD": 0.5,
    "DEFAULT_LANGUAGE": 'en-IN',
    "TRANSCRIPTION_ENGINE": 'google',
    "WHISPER_MODEL": 'large-v3-turbo',
    "BEEP_ON_START": True,
    "BEEP_ON_END": True,
    "RUN_ON_STARTUP": False,
    "PRE_ROLL_SECONDS": 0.5,
    "POST_ROLL_SECONDS": 0.5,
    "SILENCE_PADDING_MS": 200,
    "AUTO_ENERGY_THRESHOLD": True,
    "ENERGY_THRESHOLD": 300,
    # --- New SPEC parameters ---
    "SAMPLE_RATE": 16000,
    "CHANNELS": 1,
    "CHUNK_SIZE": 512,
    "HPF_CUTOFF": 100,
    "NORMALIZATION_RMS": 0.15,
    "DIGITAL_GAIN": 1.4,  # ~+3 dB boost (applied after RMS normalization)
    "NO_SPEECH_THRESHOLD": 0.6,
    "LOG_PROB_THRESHOLD": -1.0,
    "MIN_AUDIO_DURATION": 1.0, # Minimum 1s audio to process
    "VAD_THRESHOLD": 0.010,  # Voice activity detection threshold (0.008-0.020) - slightly lower for better speech detection
    "AUTO_PUNCTUATION": True,  # Append "." to transcriptions that don't end with punctuation
    "CAPITALIZE_FIRST": True,  # Capitalize first letter of each transcription
    "SPOKEN_COMMANDS": True,   # Convert "full stop"/"comma"/"new line" etc. to their symbols
    "ONBOARDING_COMPLETED": False,  # Hide the first-run wizard once user finishes it
}

# --- VALID HOTKEYS WHITELIST ---
VALID_HOTKEYS = {
    'left alt', 'right alt', 'alt gr',
    'left ctrl', 'right ctrl',
    'left shift', 'right shift',
    'left win', 'right win',
    'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm',
    'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z',
    'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12',
    'enter', 'tab', 'space', 'backspace', 'escape', 'delete',
}

# --- RANGE VALIDATORS (for numeric settings — guards against corrupted config) ---
_SETTING_RANGES = {
    "LONG_PRESS_THRESHOLD": (0.1, 2.0),       # 100ms – 2000ms (FR-001-06)
    "PRE_ROLL_SECONDS": (0.0, 2.0),           # 0s – 2s pre-roll
    "POST_ROLL_SECONDS": (0.0, 2.0),          # 0s – 2s post-roll
    "SILENCE_PADDING_MS": (0, 1000),          # 0ms – 1s padding
    "ENERGY_THRESHOLD": (1, 100000),          # mic sensitivity floor
    "SAMPLE_RATE": (8000, 48000),             # standard speech rates
    "CHANNELS": (1, 2),                       # mono or stereo only
    "CHUNK_SIZE": (128, 8192),                # must divide sample rate cleanly-ish
    "HPF_CUTOFF": (50, 500),                  # 50Hz – 500Hz high-pass
    "NORMALIZATION_RMS": (0.01, 1.0),         # 1% – 100% of full scale
    "DIGITAL_GAIN": (1.0, 5.0),               # 0dB – ~14dB boost
    "NO_SPEECH_THRESHOLD": (0.1, 1.0),
    "LOG_PROB_THRESHOLD": (-20.0, 0.0),
    "MIN_AUDIO_DURATION": (0.5, 30.0),
    "VAD_THRESHOLD": (0.001, 0.1),
    "STATUS_BAR_TIMEOUT": (0.5, 10.0),
}


# --- TYPE VALIDATORS (for settings validation) ---
_SETTING_TYPES = {
    "ACTIVATION_KEY": str,
    "LONG_PRESS_THRESHOLD": (int, float),
    "DEFAULT_LANGUAGE": str,
    "TRANSCRIPTION_ENGINE": str,
    "WHISPER_MODEL": str,
    "BEEP_ON_START": bool,
    "BEEP_ON_END": bool,
    "RUN_ON_STARTUP": bool,
    "PRE_ROLL_SECONDS": (int, float),
    "POST_ROLL_SECONDS": (int, float),
    "SILENCE_PADDING_MS": (int, float),
    "AUTO_ENERGY_THRESHOLD": bool,
    "ENERGY_THRESHOLD": (int, float),
    "SAMPLE_RATE": int,
    "CHANNELS": int,
    "CHUNK_SIZE": int,
    "HPF_CUTOFF": (int, float),
    "NORMALIZATION_RMS": (int, float),
    "DIGITAL_GAIN": (int, float),
    "NO_SPEECH_THRESHOLD": (int, float),
    "LOG_PROB_THRESHOLD": (int, float),
    "MIN_AUDIO_DURATION": (int, float),
    "VAD_THRESHOLD": (int, float),
    "AUTO_PUNCTUATION": bool,
    "CAPITALIZE_FIRST": bool,
    "SPOKEN_COMMANDS": bool,
    "ONBOARDING_COMPLETED": bool,
}

# Apply defaults initially
ACTIVATION_KEY = _DEFAULTS["ACTIVATION_KEY"]
LONG_PRESS_THRESHOLD = _DEFAULTS["LONG_PRESS_THRESHOLD"]
DEFAULT_LANGUAGE = _DEFAULTS["DEFAULT_LANGUAGE"]
TRANSCRIPTION_ENGINE = _DEFAULTS["TRANSCRIPTION_ENGINE"]
WHISPER_MODEL = _DEFAULTS["WHISPER_MODEL"]
BEEP_ON_START = _DEFAULTS["BEEP_ON_START"]
BEEP_ON_END = _DEFAULTS["BEEP_ON_END"]
RUN_ON_STARTUP = _DEFAULTS["RUN_ON_STARTUP"]
PRE_ROLL_SECONDS = _DEFAULTS["PRE_ROLL_SECONDS"]
POST_ROLL_SECONDS = _DEFAULTS["POST_ROLL_SECONDS"]
SILENCE_PADDING_MS = _DEFAULTS["SILENCE_PADDING_MS"]
AUTO_ENERGY_THRESHOLD = _DEFAULTS["AUTO_ENERGY_THRESHOLD"]
ENERGY_THRESHOLD = _DEFAULTS["ENERGY_THRESHOLD"]
SAMPLE_RATE = _DEFAULTS["SAMPLE_RATE"]
CHANNELS = _DEFAULTS["CHANNELS"]
CHUNK_SIZE = _DEFAULTS["CHUNK_SIZE"]
HPF_CUTOFF = _DEFAULTS["HPF_CUTOFF"]
NORMALIZATION_RMS = _DEFAULTS["NORMALIZATION_RMS"]
DIGITAL_GAIN = _DEFAULTS["DIGITAL_GAIN"]
NO_SPEECH_THRESHOLD = _DEFAULTS["NO_SPEECH_THRESHOLD"]
LOG_PROB_THRESHOLD = _DEFAULTS["LOG_PROB_THRESHOLD"]
MIN_AUDIO_DURATION = _DEFAULTS["MIN_AUDIO_DURATION"]
VAD_THRESHOLD = _DEFAULTS["VAD_THRESHOLD"]
AUTO_PUNCTUATION = _DEFAULTS["AUTO_PUNCTUATION"]
CAPITALIZE_FIRST = _DEFAULTS["CAPITALIZE_FIRST"]
SPOKEN_COMMANDS = _DEFAULTS["SPOKEN_COMMANDS"]
ONBOARDING_COMPLETED = _DEFAULTS["ONBOARDING_COMPLETED"]

SETTINGS_FILE = "settings.json"
HISTORY_FILE = "history.json"

_ALLOWED_SETTINGS = set(_DEFAULTS.keys())


def _is_frozen() -> bool:
    """Detect PyInstaller / cx_Freeze frozen executable."""
    return getattr(sys, 'frozen', False)


def _get_user_data_dir() -> str:
    """OS-appropriate writable data directory for Bolo user state.

    Frozen exe: %APPDATA%\\Bolo on Windows, ~/.config/bolo on Linux/macOS.
    Development: project root (lets you edit settings.json by hand).
    """
    if _is_frozen():
        if sys.platform == "win32":
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
            data_dir = os.path.join(base, "Bolo")
        elif sys.platform == "darwin":
            data_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Bolo")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
            data_dir = os.path.join(base, "bolo")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    # Dev mode: project root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_app_root() -> str:
    """Source-tree root (read-only resources only — icons, bundled models)."""
    if _is_frozen() and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_settings_path() -> str:
    return os.path.join(_get_user_data_dir(), SETTINGS_FILE)


def _get_history_path() -> str:
    return os.path.join(_get_user_data_dir(), HISTORY_FILE)


def _get_lock_path() -> str:
    return os.path.join(_get_user_data_dir(), ".bolo.lock")

def _load_settings() -> None:
    """Load settings from JSON, validating types and hotkey whitelist.

    Driven by _DEFAULTS — any key added there is auto-loaded here.
    """
    data = atomic_json_read(_get_settings_path(), default={})
    if not isinstance(data, dict):
        return

    for key, default in _DEFAULTS.items():
        if key not in data:
            continue
        value = data[key]

        if key == "ACTIVATION_KEY":
            if not isinstance(value, str) or value.lower() not in VALID_HOTKEYS:
                print(f"[Config] Invalid hotkey '{value}'. Using default '{default}'")
                continue

        expected = _SETTING_TYPES.get(key)
        if expected and not isinstance(value, expected):
            # Coerce legacy 0/1 → bool
            if expected is bool and isinstance(value, int) and value in (0, 1):
                value = bool(value)
            else:
                print(f"[Config] Type mismatch for '{key}': expected {expected}, got {type(value).__name__}. Using default.")
                continue

        # Range check for numeric settings — guards against corrupted config
        rng = _SETTING_RANGES.get(key)
        if rng is not None:
            lo, hi = rng
            if isinstance(value, bool) or value < lo or value > hi:
                print(f"[Config] '{key}'={value!r} out of range [{lo}, {hi}]. Using default '{default}'")
                continue

        globals()[key] = value

_load_settings()

def save_setting(key: str, value: Any) -> bool:
    """Validate then save a setting to disk atomically.

    Validation order: allowed key → type → hotkey whitelist → JSON serializable.
    Read-modify-write happens under the per-path lock (atomic_json_*).
    """
    if key not in _ALLOWED_SETTINGS:
        print(f"[Config] Error: Unknown setting '{key}'")
        return False

    expected_type = _SETTING_TYPES.get(key)
    if expected_type and not isinstance(value, expected_type):
        print(f"[Config] Error: Setting '{key}' expected {expected_type}, got {type(value).__name__}")
        return False

    if key == "ACTIVATION_KEY":
        if not isinstance(value, str) or value.lower() not in VALID_HOTKEYS:
            print(f"[Config] Error: Invalid hotkey '{value}'. Valid: {', '.join(sorted(VALID_HOTKEYS))}")
            return False

    # Range validation for numeric settings
    rng = _SETTING_RANGES.get(key)
    if rng is not None:
        lo, hi = rng
        if isinstance(value, bool) or value < lo or value > hi:
            print(f"[Config] Error: '{key}'={value!r} out of range [{lo}, {hi}].")
            return False

    try:
        json.dumps({key: value})
    except (TypeError, ValueError) as e:
        print(f"[Config] Error: Value for '{key}' is not JSON-serializable: {e}")
        return False

    globals()[key] = value

    settings_path = _get_settings_path()
    # Atomic read-modify-write under the per-path lock
    with _lock_for(settings_path):
        data = atomic_json_read(settings_path, default={}) or {}
        if not isinstance(data, dict):
            data = {}
        data[key] = value
        ok = atomic_json_write(settings_path, data)
    if ok:
        print(f"[Config] Saved setting '{key}' = {value}")
    return ok

def reset_settings() -> None:
    for key, val in _DEFAULTS.items():
        if key in _ALLOWED_SETTINGS:
            globals()[key] = val
    settings_path = _get_settings_path()
    try:
        if os.path.exists(settings_path):
            os.remove(settings_path)
    except OSError:
        pass

SUPPORTED_LANGUAGES = {
    # Top of menu: most-used by Indian users
    'Hinglish (English+Hindi)': 'xx-HI',
    'English (India)': 'en-IN',
    'Hindi (Devanagari)': 'hi-IN',
    # Regional languages (alphabetical)
    'Bengali': 'bn-IN',
    'Gujarati': 'gu-IN',
    'Kannada': 'kn-IN',
    'Malayalam': 'ml-IN',
    'Marathi': 'mr-IN',
    'Odia': 'or-IN',
    'Punjabi': 'pa-IN',
    'Tamil': 'ta-IN',
    'Telugu': 'te-IN',
}

TRANSCRIPTION_ENGINES = {
    'Google Speech (Online)': 'google',
    'Whisper AI (Local - Accurate)': 'whisper'
}

WHISPER_MODELS = ['tiny', 'base', 'small', 'medium', 'large-v2', 'large-v3', 'large-v3-turbo', 'distil-large-v2', 'distil-large-v3']

WHISPER_MODEL_DESCRIPTIONS = {
    'tiny': 'Fastest, least accurate. Best for English only.',
    'base': 'Fast, basic accuracy. Good for simple English.',
    'small': 'Good balance of speed & accuracy.',
    'medium': 'More accurate, slower. Decent multilingual.',
    'large-v2': 'High accuracy, slow. Strong multilingual.',
    'large-v3': 'Best accuracy, slowest. Best multilingual.',
    'large-v3-turbo': 'Best speed+accuracy balance. Excellent for Hinglish/multilingual.',
    'distil-large-v2': 'Faster than large-v2, slightly less accurate.',
    'distil-large-v3': 'Fastest large option, good multilingual.',
}

# UI Settings
STATUS_BAR_TIMEOUT = 1.5
THEME = "dark"
COLOR_THEME = "red"
WINDOW_SIZE = "780x640"

# Colors — Premium Windows 11 Dark Theme
ACCENT_COLOR = "#FF3131"
SUCCESS_COLOR = "#10b981"
ERROR_COLOR = "#ef4444"
RECORDING_COLOR = "#FF3131"
SIDEBAR_BG = "#161617"
CONTENT_BG = "#0c0c0d"
CARD_BG = "#1a1a1d"
SURFACE_BG = "#121214"
TEXT_MUTED = "#6b6b70"
TEXT_PRIMARY = "#f4f4f6"
BORDER_COLOR = "#2a2a2e"
GLOW_COLOR = "#FF3131"

# Fonts
FONT_FAMILY = "Segoe UI Variable Display, Segoe UI, Inter, Helvetica"

# Layout
SIDEBAR_WIDTH = 190
CORNER_RADIUS = 20
PADDING_LARGE = 24
PADDING_MEDIUM = 16
PADDING_SMALL = 10

# Data Storage
MAX_HISTORY = 50
MINIMIZE_TO_TRAY_ON_CLOSE = True

# Zero-STT Hinglish Model
# Models stay in user data dir (writable, persists across reinstall)
ZERO_STT_MODEL_ID = "shunyalabs/zero-stt-hinglish"
ZERO_STT_CACHE_DIR = os.path.join(_get_user_data_dir(), "models")
ZERO_STT_MODEL_PATH = os.path.join(ZERO_STT_CACHE_DIR, "zero-stt-hinglish-ct2")
