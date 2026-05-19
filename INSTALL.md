# Installing Bolo

Bolo is a Windows voice-to-text app for Indian languages and Hinglish. This
guide is for **end users** who just want to install and use Bolo — no Python
or developer tools required.

## System requirements

| Item       | Minimum                              |
|------------|--------------------------------------|
| OS         | Windows 10 21H2+ or Windows 11       |
| RAM        | 4 GB (8 GB recommended)              |
| Disk       | 3 GB free (for the app + models)     |
| GPU        | Optional — NVIDIA CUDA for faster local STT |
| Microphone | Required                             |
| Internet   | Needed only for Google Speech engine and first-run Hinglish model download |

## Quick install (5 minutes)

1. **Download all release assets** from:
   👉 https://github.com/ssdevstudio/bolo-voice-to-text/releases/latest

   The `.exe` is split across multiple files because it's > 2 GB. Download
   **every file** in the release:
   - `Bolo-v1.2.0.7z.001`  (~1.9 GB)
   - `Bolo-v1.2.0.7z.002`  (~600 MB)
   - (more `.00N` files if present)

   Keep **all parts in the same folder** — order matters.

2. **Install 7-Zip** if you don't have it:
   - Microsoft Store → search "7-Zip" → install (free)
   - or https://www.7-zip.org/

3. **Right-click `Bolo-v1.2.0.7z.001`** → **7-Zip → Extract Here**
   7-Zip auto-picks up the other `.002`/`.003` parts. You'll get a single
   `Bolo.exe`.

4. **Move `Bolo.exe`** anywhere convenient — for example:
   - `C:\Apps\Bolo\` (recommended)
   - or your Desktop

5. **First launch**:
   - Double-click `Bolo.exe`
   - Wait 30–60 seconds on the very first run (Windows scans the executable)
   - Allow microphone access if Windows prompts
   - The onboarding wizard will guide you through language selection

6. **Start dictating**:
   - Click into any text field (browser, email, Notepad, anything)
   - Hold **Right Alt** and speak
   - Release — your words appear at the cursor

## Troubleshooting

### "Windows protected your PC" / SmartScreen warning

Bolo isn't code-signed yet (signing costs ~$200/yr for a code-signing cert).
SmartScreen flags unknown publishers by default.

1. Click **More info**
2. Click **Run anyway**

This is a one-time prompt per machine.

### Hotkey doesn't trigger recording

- Some apps grab the Right Alt key — try Left Alt or F12 from Settings
- On EU keyboard layouts, Right Alt = AltGr → use a different hotkey
- Run Bolo as Administrator if your target app runs elevated (e.g., Task Manager)

### "Could not understand audio" repeatedly

- Check your default microphone in Windows Sound settings
- In Bolo's dashboard, the volume bar should react when you speak
- If silent, click the tray icon → "Reconnect Mic"

### Hinglish gives weird output

- Switch the engine to Google Speech in Settings (better English/Hindi mix)
- For pure Hindi, pick "Hindi (Devanagari)" instead

### App doesn't appear after launch

- Check the system tray (bottom-right) for the Bolo icon
- The dashboard window is hidden by default to save screen space
- Click the tray icon → Dashboard to open it

### Logs and settings location

| Item     | Path                                       |
|----------|--------------------------------------------|
| Logs     | `%APPDATA%\Bolo\logs\Bolo.log`             |
| Settings | `%APPDATA%\Bolo\settings.json`             |
| History  | `%APPDATA%\Bolo\history.json`              |
| Models   | `%APPDATA%\Bolo\models\`                   |

Open a folder by pressing `Win+R`, typing the path, and pressing Enter.

## Uninstall

1. Close Bolo (right-click tray icon → Exit)
2. Delete the extracted folder
3. (Optional) Delete `%APPDATA%\Bolo\` to remove settings, history, and downloaded models
4. (Optional) Remove the Windows startup entry if you enabled "Run on Startup":
   - `Win+R` → `shell:startup` → delete the Bolo shortcut

## Privacy

- **Google Speech engine**: Audio is sent to Google's servers for transcription.
- **Whisper / Zero-STT engine**: Everything runs on your machine. No audio leaves your device.
- **History**: Stored locally in `%APPDATA%\Bolo\history.json`. Never uploaded.
- **Microphone**: Bolo only listens while you hold the activation key.

## Need help?

- Report bugs / request features: https://github.com/ssdevstudio/bolo-voice-to-text/issues
