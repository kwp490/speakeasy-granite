# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.13.x  | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in SpeakEasy AI, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Please use [GitHub's private vulnerability reporting](https://github.com/kwp490/speakeasy-granite/security/advisories/new) to report the issue privately to the maintainer.

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
- **Defender exclusions**: Installers do not add Microsoft Defender exclusions by default. If Defender quarantines `speakeasy.exe` after you have verified the installer checksum and trust the release source, you can add a temporary process exclusion manually and remove it after Microsoft Defender definitions or the app package are updated.
- **`uv.exe` false positives**: Some anti-malware tools (e.g. Malwarebytes) may quarantine `uv.exe` during source installs. If this happens, restore it and add it to your allow list. [uv](https://github.com/astral-sh/uv) is a widely used open-source Python package manager.
- **API key handling (Professional Mode)**: OpenAI API keys entered in Settings are held in memory only by default and are **never** written to `settings.json` or any log file. If "Remember API key" is enabled, the key is stored via Windows Credential Manager (protected by Windows DPAPI encryption). API keys are never displayed in the UI log panel, and all error messages are sanitized to redact key content.
- **Single-instance mutex**: A Windows named mutex (`Global\SpeakEasyAIGraniteMutex`) prevents multiple SpeakEasy AI Granite processes from running simultaneously, avoiding resource conflicts.

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `SPEAKEASY_HOME` | Overrides the install directory; when set, **all** mutable data (config, models, logs) is stored under this path instead of `%ProgramData%`. Used by the source-install workflow (`dev-temp/`). | Not set (production default) |
| `PROGRAMDATA` | Standard Windows variable. Production installs store mutable data under `%ProgramData%\SpeakEasy AI Granite`. | `C:\ProgramData` |

No other environment variables are read or set at runtime by the application itself. (The PyInstaller frozen build sets `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, and appends to `PATH` during process startup for bundled DLL and certificate resolution.)

## Manual Defender Troubleshooting

Only use a Defender process exclusion if Microsoft Defender quarantines a verified SpeakEasy AI Granite install. Prefer submitting the detection to Microsoft as a false positive when possible.

Add a process exclusion for the installed app:

```powershell
Add-MpPreference -ExclusionProcess "C:\Program Files\SpeakEasy AI Granite\speakeasy.exe"
```

Remove the process exclusion when it is no longer needed:

```powershell
Remove-MpPreference -ExclusionProcess "C:\Program Files\SpeakEasy AI Granite\speakeasy.exe"
```

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

**Network**: SpeakEasy AI makes network requests **only** in these scenarios:

1. **Model downloads** — to HuggingFace Hub when downloading the IBM Granite Speech model. A token may be supplied if HuggingFace denies anonymous access.
2. **Professional Mode** (when enabled) — transcribed text is sent to the OpenAI API (`api.openai.com`) for tone, grammar, and punctuation cleanup. This requires a user-provided API key and is **opt-in only** — disabled by default. No audio data is sent; only the transcribed text string is transmitted.
3. **Remote ASR mode** (when enabled) — recorded audio is sent to a user-operated SpeakEasy transcription server and the transcribed text is returned. This is **opt-in only**, disabled by default, and requires an explicit one-time disclosure acknowledgement (see [Remote ASR mode](#remote-asr-mode) below and [docs/REMOTE.md](docs/REMOTE.md)).

No telemetry, analytics, or usage data is collected or transmitted.

## Remote ASR mode

Remote ASR mode (`speakeasy serve` + the in-app *Remote* model source) lets one machine run the
Granite engine and serve transcription to one or more clients over HTTP. It is **disabled by
default** and never engages unless the user explicitly selects a Remote model source and accepts the
privacy disclosure dialog.

### What leaves the machine

- In remote mode **only**: recorded audio (16 kHz mono PCM16 WAV) is transmitted to the configured
  server, and the resulting transcript text is returned. In all local engine modes, audio never
  leaves the machine.
- The disclosure dialog must be accepted once (`remote_disclosure_accepted` in `settings.json`)
  before any audio is sent. Changing the remote URL re-shows the dialog.

### Threat model & controls

- **Authentication**: every request carries an `Authorization: Bearer <token>` header. The server
  rejects mismatched tokens with HTTP 401 using a constant-time comparison
  (`secrets.compare_digest`) to avoid timing oracles.
- **Network exposure**: the server binds to `127.0.0.1` (loopback) by default. Binding to a
  non-loopback address requires **both** `--allow-remote` **and** a token; the server refuses to
  start in an unsafe configuration (non-loopback bind without a token) with a `ValueError`.
- **Token storage**: the client stores the bearer token in the OS keyring (Windows Credential
  Manager, service `speakeasy`, key `remote_asr_token`) — never in `settings.json` or logs. The
  server token is generated with `secrets.token_urlsafe(32)` via `--generate-token`.
- **Transport**: HTTP is plaintext. For any link beyond a trusted LAN, run the server behind a TLS
  terminator (reverse proxy) or an SSH/WireGuard tunnel and point the client at the `https://`
  endpoint. The bearer token alone does **not** protect audio confidentiality on the wire.
- **Request limits**: request bodies are capped (16 MB default) and rejected with HTTP 413 to bound
  memory use. A single inference lock serializes transcription so one client cannot starve the GPU
  with concurrent requests; excess work queues rather than over-subscribing the device.
- **No persistence**: the server processes audio in memory and returns the transcript; it does not
  write audio or transcripts to disk. Server logs contain diagnostic data only (no speech content).

Operating a server reachable from hostile networks is the operator's responsibility — see
[docs/REMOTE.md](docs/REMOTE.md) for hardening guidance (firewall, TLS, tunnels).
