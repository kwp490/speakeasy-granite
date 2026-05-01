# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.5.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in SpeakEasy AI, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, email the maintainer directly or use [GitHub's private vulnerability reporting](https://github.com/kwp490/SpeakEasyAI/security/advisories/new).

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response timeline

- **Acknowledgment**: within 48 hours
- **Initial assessment**: within 1 week
- **Fix or mitigation**: depends on severity, typically within 2 weeks for critical issues

## Known Security Considerations

- **Hotkeys**: Global hotkeys are registered via the Win32 `RegisterHotKey` API — only the configured chord is delivered to the application. No low-level keyboard hook (`WH_KEYBOARD_LL` / `SetWindowsHookEx`) is installed; no keystrokes beyond the registered chords are captured or logged.
- **Administrator privileges**: The installer requires elevation to write to `C:\Program Files\SpeakEasy AI Granite`.
- **Defender exclusions**: The GUI installer adds a Windows Defender **process** exclusion for `speakeasy.exe` only (not the entire install directory) to prevent false-positive detections common to PyInstaller binaries. The exclusion is removed on uninstall.
- **`uv.exe` false positives**: Some anti-malware tools (e.g. Malwarebytes) may quarantine `uv.exe` during source installs. If this happens, restore it and add it to your allow list. [uv](https://github.com/astral-sh/uv) is a widely used open-source Python package manager.
- **API key handling (Professional Mode)**: OpenAI API keys entered in Settings are held in memory only by default and are **never** written to `settings.json` or any log file. If "Remember API key" is enabled, the key is stored via Windows Credential Manager (protected by Windows DPAPI encryption). API keys are never displayed in the UI log panel, and all error messages are sanitized to redact key content.
- **Single-instance mutex**: A Windows named mutex (`Global\SpeakEasyAIGraniteMutex`) prevents multiple SpeakEasy AI Granite processes from running simultaneously, avoiding resource conflicts.

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `SPEAKEASY_HOME` | Overrides the install directory; when set, **all** mutable data (config, models, logs) is stored under this path instead of `%ProgramData%`. Used by the source-install workflow (`dev-temp/`). | Not set (production default) |
| `PROGRAMDATA` | Standard Windows variable. Production installs store mutable data under `%ProgramData%\SpeakEasy AI Granite`. | `C:\ProgramData` |

No other environment variables are read or set at runtime by the application itself. (The PyInstaller frozen build sets `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, and appends to `PATH` during process startup for bundled DLL and certificate resolution.)

## Privacy & Data Handling

**Audio**: Recorded audio is processed entirely in memory as numpy arrays and in-memory `BytesIO` WAV buffers. Audio data is discarded after transcription. No audio files are written to disk.

**Transcriptions**: Transcribed text is displayed in the UI and optionally copied to the clipboard. Transcription content is **not** written to log files — only character counts are logged. When **Professional Mode** is enabled, transcribed text is sent to the OpenAI API for cleanup (see Network below).

**Logs**: Application logs are written to `%LOCALAPPDATA%\SpeakEasy AI Granite\logs\speakeasy.log` (per-user) as a rotating file (2 MB per file, up to 2 backups, roughly 6 MB max). Logs contain diagnostic information (engine status, GPU metrics, error traces) but **no** speech content. Logs are deleted on exit by default (`clear_logs_on_exit: true` in settings). Using a per-user directory prevents cross-user log access on shared machines.

**On-disk data locations (production install)**:

| Path | Contents |
|---|---|
| `C:\Program Files\SpeakEasy AI Granite\` | Read-only application binaries |
| `%ProgramData%\SpeakEasy AI Granite\config\` | `settings.json`, user preset JSON files |
| `%ProgramData%\SpeakEasy AI Granite\models\` | Downloaded model weights |
| `%LOCALAPPDATA%\SpeakEasy AI Granite\logs\` | Rotating log files (per-user) |

The Inno Setup uninstaller removes `config\`, `models\`, and the application directory. Per-user logs under `%LOCALAPPDATA%` are not removed by the system-level uninstaller.

**Network**: SpeakEasy AI makes network requests **only** in two scenarios:

1. **Model downloads** — to HuggingFace Hub when downloading the IBM Granite Speech model. A token may be supplied if HuggingFace denies anonymous access.
2. **Professional Mode** (when enabled) — transcribed text is sent to the OpenAI API (`api.openai.com`) for tone, grammar, and punctuation cleanup. This requires a user-provided API key and is **opt-in only** — disabled by default. No audio data is sent; only the transcribed text string is transmitted.

No telemetry, analytics, or usage data is collected or transmitted.
