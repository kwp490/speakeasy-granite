# SpeakEasy AI — Native Windows Voice-to-Text

*Clean transcripts. Fewer corrections. Runs privately on your own machine.*

**Accurate, fast speech-to-text for Windows, powered by the Cohere Transcribe model.**

Press a hotkey, speak, and your transcribed text is pasted into the active window. Runs locally with NVIDIA CUDA acceleration or on CPU alone — no cloud, no subscription, no setup complexity.

## Why SpeakEasy AI

SpeakEasy AI is built around a single goal: accurate transcription that you can trust. The Cohere Transcribe model it uses has been benchmarked against Whisper Large v3 — a widely adopted open-source ASR baseline — and delivers meaningfully fewer transcription errors.

| Model                                   | Word Error Rate (WER) |
| --------------------------------------- | --------------------- |
| **Cohere Transcribe 03-2026**           | **5.42%**             |
| Whisper Large v3                        | 7.44%                 |

*Word Error Rate (WER) measures the percentage of words transcribed incorrectly — lower is better. Based on publicly reported benchmark results. You can verify and explore the full rankings on the [Open ASR Leaderboard](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard).*

The difference corresponds to roughly **27% fewer transcription errors** relative to Whisper Large v3. In practice, that means less time correcting output and more accurate text the first time.

Other reasons to use SpeakEasy AI:

- **Private by design** — audio is processed locally; nothing leaves your machine
- **Runs anywhere** — GPU (CUDA) for fast inference, or CPU-only on any Windows PC
- **Easy setup** — double-click installer, paste a HuggingFace token, and you're running
- **Auto-paste** — transcribed text goes directly into the active window, no copy-paste needed
- **Professional Mode** — optional AI post-processing to clean tone, grammar, and punctuation

## Getting Started

There are two ways to install SpeakEasy AI: download the pre-built installer (recommended), or build from source. Both methods support GPU and CPU-only variants.

**Requirements (both methods):** Windows 10/11 (64-bit), [HuggingFace account](https://huggingface.co/join) with access to [CohereLabs/cohere-transcribe-03-2026](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026). An NVIDIA GPU (RTX 30-series or newer, 6+ GB VRAM, Driver 525+) is recommended for fast inference but not required — the app can run on CPU (slower).

### Option 1 — Installer (recommended)

| Variant               | Download                                         | Requirements                                 |
| --------------------- | ------------------------------------------------ | -------------------------------------------- |
| **GPU** (recommended) | [SpeakEasy-AI-Setup-0.7.3.exe][gpu-installer]     | NVIDIA GPU (RTX 30+, 6 GB VRAM, Driver 525+) |
| **CPU**               | [SpeakEasy-AI-CPU-Setup-0.7.3.exe][cpu-installer] | No GPU required (slower inference)           |

[gpu-installer]: https://github.com/kwp490/speakeasy-ai/releases/download/v0.7.3/SpeakEasy-AI-Setup-0.7.3.exe
[cpu-installer]: https://github.com/kwp490/speakeasy-ai/releases/download/v0.7.3/SpeakEasy-AI-CPU-Setup-0.7.3.exe

Double-click the installer and follow the prompts. No Python, no command line required. The installer will:

1. Extract application files to `C:\Program Files\SpeakEasy AI`
2. Prompt for your HuggingFace API token (required for gated model access)
3. Download the Cohere Transcribe speech model from HuggingFace
4. Create desktop and Start Menu shortcuts
5. Configure Windows Defender exclusions

> **Note:** Both variants install to the same directory and share the same App ID. Installing one replaces the other — they cannot coexist side-by-side.

### Option 2 — Run from source

For developers or users who prefer to build and run from source. Requires [Git](https://git-scm.com/downloads/win) and [uv](https://docs.astral.sh/uv/) (installed in step 1 below).

**GPU (default — requires NVIDIA GPU with CUDA):**

```powershell
# 1. Install uv (Python package manager)
irm https://astral.sh/uv/install.ps1 | iex

# 2. Clone and install dependencies
git clone https://github.com/kwp490/speakeasy-ai.git
cd speakeasy-ai
uv sync

# 3. Download the model and launch
uv run speakeasy download-model --token YOUR_HF_TOKEN
uv run speakeasy
```

**CPU-only (no GPU required):**

```powershell
# Steps 1-2 are the same as above, then replace CUDA torch with CPU-only torch:
uv pip install --index-url https://download.pytorch.org/whl/cpu --upgrade --force-reinstall torch

# Download the model and launch
uv run speakeasy download-model --token YOUR_HF_TOKEN
uv run speakeasy
```

Or use the automated source installer (requires admin):

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\installer\Install-SpeakEasy-Source.ps1              # interactive prompt
.\installer\Install-SpeakEasy-Source.ps1 -Variant CPU  # CPU-only, no GPU required
.\installer\Install-SpeakEasy-Source.ps1 -Variant GPU  # GPU with CUDA acceleration
```

### Option 3 — Build the installer yourself

To compile a distributable installer (PyInstaller + Inno Setup), use the build script. Requires [Inno Setup](https://jrsoftware.org/isinfo.php) on PATH.

```powershell
.\installer\Build-Installer.ps1                          # GPU installer (default)
.\installer\Build-Installer.ps1 -Variant CPU              # CPU-only installer
.\installer\Build-Installer.ps1 -Variant Both             # Build both sequentially
.\installer\Build-Installer.ps1 -Variant Both -Fast       # Both, fast compression (dev builds)
```

Output installers are written to `installer\Output\`.

> **Optional performance boost:** Install [AIM Toolkit](https://sourceforge.net/projects/aim-toolkit/) to enable automatic RAM disk acceleration during builds. If a RAM disk is mounted as `R:`, the build script redirects intermediate files there, significantly reducing I/O time. AIM Toolkit supersedes ImDisk Toolkit for recent Windows versions.

## Features

- **Cohere Transcribe 03-2026**: 2B-parameter ASR model, 14 languages, ~5 GB VRAM — benchmarked at 5.42% WER (see [Why SpeakEasy AI](#why-speakeasy-ai) above)
- **Professional Mode**: AI-powered text cleanup via OpenAI API with a preset system — 5 built-in presets, custom presets, domain vocabulary preservation, and per-preset model selection
- **Punctuation control**: Enable or disable automatic punctuation in transcription output
- **Global hotkeys**: Start/stop recording from any application (configurable bindings)
- **Auto-paste**: Transcribed text goes directly to your active window
- **GPU-accelerated**: Leverages NVIDIA CUDA for fast inference
- **Microphone selection**: Choose a specific input device or use the system default
- **Sleep/wake recovery**: Hotkeys automatically re-register after Windows resume from sleep
- **Single-instance guard**: Prevents multiple SpeakEasy AI processes from running simultaneously
- **Real-time resource monitoring**: RAM, VRAM, and GPU temperature displayed in the diagnostics panel
- **Audio feedback**: Beep tones on recording start/stop
- **GPU and CPU variants** — GPU installer with CUDA acceleration, or lightweight CPU-only installer
- **Runs natively on Windows** — no dependencies

## Settings

| Setting              | Default                                | Description                                      |
| -------------------- | -------------------------------------- | ------------------------------------------------ |
| `engine`             | `cohere`                               | Speech engine (Cohere Transcribe)                |
| `model_path`         | `%ProgramData%\SpeakEasy AI\models`    | Directory for model weights                      |
| `device`             | `cuda` (GPU) / `cpu` (CPU)             | Inference device — GPU builds default to `cuda` and allow `cpu` fallback; CPU builds are locked to `cpu` |
| `language`           | `en`                                   | Language code                                    |
| `punctuation`        | `true`                                 | Enable automatic punctuation in transcription    |
| `inference_timeout`  | `30`                                   | Max seconds per transcription                    |
| `auto_copy`          | `true`                                 | Auto-copy transcription to clipboard             |
| `auto_paste`         | `true`                                 | Auto-paste via Ctrl+V after transcription        |
| `hotkeys_enabled`    | `true`                                 | Master toggle for global hotkeys                 |
| `hotkey_start`       | `ctrl+alt+p`                           | Record toggle hotkey (start or stop recording)   |
| `hotkey_quit`        | `ctrl+alt+q`                           | Quit application hotkey                          |
| `clear_logs_on_exit` | `true`                                 | Clear log files when the application exits       |
| `mic_device_index`   | `-1`                                   | Microphone device index (`-1` = system default)  |
| `sample_rate`        | `16000`                                | Recording sample rate (Hz) - resampled to 16 kHz |
| `silence_threshold`  | `0.0015`                               | RMS threshold for silence detection              |
| `silence_margin_ms`  | `500`                                  | Silence margin (ms) added around voiced regions  |
| `professional_mode`  | `false`                                | Enable AI text cleanup (requires OpenAI API key) |
| `pro_active_preset`  | `General Professional`                 | Active Professional Mode preset name             |
| `store_api_key`      | `false`                                | Persist API key in Windows Credential Manager    |

Settings are stored at `%ProgramData%\SpeakEasy AI\config\settings.json`.

> **Note:** The OpenAI API key is **never** stored in `settings.json`. It is held in memory only, unless you enable "Remember API key", which saves it securely via Windows Credential Manager (DPAPI).

## Hotkeys

| Hotkey (default)     | Action                               |
| -------------------- | ------------------------------------ |
| `Ctrl+Alt+P`         | Toggle recording (start / stop & transcribe) |
| `Ctrl+Alt+Q`         | Quit application                             |

All hotkey bindings are configurable in Settings. Hotkeys can also be disabled entirely via the `hotkeys_enabled` toggle. After Windows resumes from sleep, hotkeys are automatically re-registered.

## Professional Mode

Optional AI-powered post-processing that cleans up your dictated text before it reaches the clipboard. Configure it via the **Professional Mode Settings** button in the main window.

> **⚠ Data Privacy — text leaves this machine.**
> When Professional Mode is active, each dictation result is transmitted to **api.openai.com** under your personal OpenAI API key — bypassing any corporate OpenAI tenant, Azure OpenAI endpoint, or DLP controls. Do not dictate confidential content — including personal data (PII/PHI), financial records, proprietary business information, or content that identifies colleagues or customers — unless you are authorised to share it with an external AI service under your personal account. SpeakEasy will display this notice the first time you enable the feature.

**What it does:**
- **Fix tone** — rewrites emotional, aggressive, or unprofessional language while preserving meaning
- **Fix grammar** — corrects grammar errors
- **Fix punctuation** — adds proper punctuation and capitalization
- **Custom instructions** — free-text system prompt per preset for fine-tuning AI behavior
- **Vocabulary preservation** — domain-specific terms (comma/newline-separated) are preserved verbatim during cleanup

Each option is configured per preset — you can have different cleanup rules for different contexts. When enabled, the transcription history shows both the original and cleaned text.

### Presets

Five built-in presets are included:

| Preset                      | Description                                                   |
| --------------------------- | ------------------------------------------------------------- |
| **General Professional**    | Neutral business tone, clear and concise                      |
| **Technical / Engineering** | Preserves jargon, acronyms, and technical terminology         |
| **Casual / Friendly**       | Warm, approachable, conversational tone                       |
| **Email / Correspondence**  | Professional email with greeting/sign-off, short paragraphs  |
| **Simplified (8th Grade)**  | Short sentences, common words, simple structures              |

You can also create, duplicate, and delete custom presets. Each preset has its own toggle settings, custom system prompt, vocabulary list, and optional model override.

**Requirements:** An OpenAI API key. Enter it in Professional Mode Settings — the key is held in memory only by default and is **never** written to `settings.json` or any log file. Optionally check "Remember API key" to store it securely via Windows Credential Manager.

## Architecture

```
┌─────────────────────────────────────────────┐
│       SpeakEasy AI GUI  (PySide6 / Qt)      │
│ ┌────────────┐  ┌──────────────────┐       │
│ │ Hotkey Mgr │  │ Resource Monitor │       │
│ │ (sleep/    │  │ (RAM + VRAM +    │       │
│ │  wake safe)│  │  GPU temp)       │       │
│ └────────────┘  └──────────────────┘       │
├────────────────────────────────────────────┤
│   Engine: Cohere Transcribe (transformers) │
│   ┌───────────────────────────────────┐    │
│   │ Cohere Transcribe 03-2026         │    │
│   │ (2B params, ~5 GB VRAM, 14 langs) │    │
│   └────────────────┬──────────────────┘    │
│                    ▼                       │
│        NVIDIA GPU (CUDA) / CPU             │
├────────────────────────────────────────────┤
│   Professional Mode (optional)             │
│   ┌──────────────────────────────────────┐ │
│   │ ProPreset → TextProcessor →          │ │
│   │ OpenAI API                           │ │
│   │ (5 built-in + custom presets,        │ │
│   │  vocabulary, custom prompts)         │ │
│   └──────────────────────────────────────┘ │
└────────────────────────────────────────────┘
```

## Supported Languages

Cohere Transcribe supports 14 languages:

| Code | Language   | Code | Language    |
|------|------------|------|-------------|
| `en` | English    | `el` | Greek       |
| `fr` | French     | `nl` | Dutch       |
| `de` | German     | `pl` | Polish      |
| `it` | Italian    | `zh` | Chinese     |
| `es` | Spanish    | `ja` | Japanese    |
| `pt` | Portuguese | `ko` | Korean      |
| `vi` | Vietnamese | `ar` | Arabic      |

## Antivirus & Anti-Malware Notes

Some antivirus products may flag the PyInstaller-packaged `.exe` as suspicious. This is a known false positive common to all PyInstaller applications. You can:

1. Add `C:\Program Files\SpeakEasy AI` to your antivirus exclusion list
2. The installer automatically configures Windows Defender exclusions

## License

[MIT](LICENSE)

## Acknowledgments

- **Florian** — for coming up with the name *SpeakEasy*
- **Joel, Carter, and Rollo** — for the *Professional Mode* idea
- **Cohere Labs** — for the [Cohere Transcribe 03-2026](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026) speech recognition model
- **Anthropic (Claude) and OpenAI (ChatGPT/Copilot)** — this application was developed with AI coding assistance from Anthropic (Claude) and OpenAI (ChatGPT/Copilot)
