# Bolo — Voice-to-Text for India

Bolo is a Windows desktop app that lets you dictate text directly into any
focused input field using your voice. It supports **12 Indian languages plus
Hinglish** (Hindi–English code-switching) and runs both **cloud STT** (Google
Speech) and **local STT** (Whisper / Zero-STT-Hinglish, GPU-accelerated).

Hold a key. Speak. Release. Your words land where the cursor is.

---

## For end users — just want to use it

👉 **[INSTALL.md](INSTALL.md)** — download the pre-built `.exe` from the
[Releases page](https://github.com/ssdevstudio/bolo-voice-to-text/releases/latest)
and follow the 5-minute quick-install guide. No Python or developer tools
needed.

---

## For developers — run from source

### Prerequisites

- Python 3.10+ (3.13 tested)
- Windows 10/11 (Linux/macOS not yet supported)
- Optional: NVIDIA GPU with CUDA for faster local STT

### Install

```powershell
git clone https://github.com/ssdevstudio/bolo-voice-to-text.git
cd bolo-voice-to-text
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Run

```powershell
python main.py
```

The system tray icon will appear; the dashboard window opens on first launch.

### Test

```powershell
python -X utf8 tests/test_hinglish_cleanup.py
```

52 regression tests covering the Hinglish cleanup pipeline.

### Build the `.exe`

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

Output: `dist/Bolo.exe` (~2.6 GB — bundles torch + CUDA + faster-whisper +
transformers). The build is driven entirely by `Bolo.spec`.

---

## Features

| Area              | Details                                                          |
|-------------------|------------------------------------------------------------------|
| Hotkey            | Configurable (default Right Alt); 100–1000 ms long-press         |
| Languages         | Hinglish, English (India), Hindi, Bengali, Tamil, Telugu, Marathi, Gujarati, Kannada, Malayalam, Odia, Punjabi |
| Engines           | Google Speech (cloud) and Whisper / Zero-STT-Hinglish (local)    |
| Injection         | Clipboard paste (multi-line / unicode) or direct keystroke type  |
| Spoken commands   | "comma", "full stop", "new line", "question mark" etc.           |
| GUI               | Modern customtkinter dashboard + pystray tray                    |
| Onboarding        | First-run 4-page wizard (welcome / mic test / language / practice) |
| Persistence       | Atomic JSON IO with per-path locks; settings + history in `%APPDATA%\Bolo\` |
| Auto-startup      | Optional Windows Run-on-Startup registry entry                    |

---

## Architecture

```
main.py              # single-instance lock, lifecycle, signal handling
src/
  config.py          # atomic JSON IO, settings, default values
  audio_engine.py    # PyAudio capture, STT pipeline, Hinglish polisher (60+ phonetic rules)
  hotkey_monitor.py  # keyboard hook, HWND capture for accurate injection
  injector.py        # focus restore + clipboard paste / direct keystroke fallback
  gui.py             # dashboard / history / settings (customtkinter)
  tray_icon.py       # pystray menu + waveform status overlay
  onboarding.py      # first-run wizard
  utils.py           # rotating log file + stdout/stderr capture
tests/
  test_hinglish_cleanup.py  # 52 regression cases (English-word safety, ITRANS quirks, etc.)
```

## Project documents

- [Bild_PRD_v1.0.md](Bild_PRD_v1.0.md) — original product requirements
- [INSTALL.md](INSTALL.md) — end-user install guide
- [LICENSE](LICENSE) — MIT
