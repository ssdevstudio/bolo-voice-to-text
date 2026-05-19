# Bolo - Voice-to-Text for India

Bolo is a lightweight desktop application that allows you to dictate text in 12 Indian languages (including Hinglish) and inject it directly into any active input field.

## Features
- **One-Key Activation**: Hold the configured key to record, release to transcribe and inject.
- **Modern Dashboard**: A premium GUI to manage settings, languages, and history.
- **Dual Engine**: Google Speech (online) or Whisper AI (local, offline).
- **Hinglish Mode**: Automatically handles Hindi-English code-switching with Devanagari-to-Roman transliteration.
- **History Log**: Keeps track of your recent transcriptions.
- **Universal Injection**: Works in any app.
- **Floating Status**: Real-time feedback overlay.

## How to Use
1. **Run the App**:
   ```bash
   python main.py
   ```
   This opens the **Bolo Dashboard** and adds an icon to your system tray.
2. **Configure**:
   - Select a language in the Dashboard (Hinglish, English, Hindi, Bengali, Telugu, etc.).
   - Choose your transcription engine (Google or Whisper).
3. **Dictate**:
   - Focus on any text field.
   - **Hold the activation key** (default: Left Alt).
   - Speak naturally.
   - **Release** to paste the text.

## Requirements
- Python 3.10+
- Internet connection (for Google Speech API; Whisper works offline)
- Microphone access
- Windows 10/11

## Installation
```bash
pip install -r requirements.txt
```

## Configuration
You can modify `src/config.py` to adjust defaults, or use the Settings panel in the GUI to change:
- Activation key (Left Alt, Right Alt, Ctrl, Shift, Space)
- Transcription engine (Google Speech / Whisper AI)
- Whisper model size
- Beep sounds
- Run on startup