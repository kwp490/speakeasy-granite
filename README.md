# SpeakEasy AI Granite: Highest-Accuracy Local Dictation for Windows

SpeakEasy AI Granite is a native Windows speech-to-text application built around IBM Granite Speech 4.1 2B, one of the strongest open ASR models currently available. It is designed for accurate real-world dictation, reliable local processing, and fast handoff into the application you are already using.

SpeakEasy records a completed utterance, transcribes it locally, copies the final text to the clipboard, and can paste it directly into the active application.

## Accuracy

SpeakEasy uses [ibm-granite/granite-speech-4.1-2b](https://huggingface.co/ibm-granite/granite-speech-4.1-2b), one of the most accurate speech-to-text models currently available on the Hugging Face Open ASR Leaderboard. The app runs this model locally through Hugging Face Transformers and PyTorch.

WER, or Word Error Rate, measures how many words in a transcript are wrong, missing, or inserted compared with a reference transcript. Lower is better; a 5% WER means roughly 5 word-level errors per 100 reference words.

The values below are representative public benchmark results and should be treated as approximate unless a current leaderboard value is shown. ASR leaderboards change as models, prompts, decoding settings, and evaluation harnesses are updated.

| Model | Word Error Rate (WER) | Notes |
| --- | ---: | --- |
| SpeakEasy AI Granite | 5.33 | Uses IBM Granite Speech 4.1 2B locally. Current Open ASR Leaderboard mean WER reported for `ibm-granite/granite-speech-4.1-2b` on 2026-04-23. |
| Whisper | Approx. 7-10 | Representative range for large Whisper-family checkpoints across mixed public ASR benchmarks. Strong general-purpose baseline, but older than current leaderboard-leading ASR models. |
| NVIDIA NeMo / Nemotron speech models | Approx. 6-12 | Results vary by checkpoint and deployment recipe. NeMo is a toolkit and model family rather than one fixed ASR model. |
| NVIDIA Canary | Approx. 6-8 | Multilingual NVIDIA ASR/translation model family. Often strong on long-form and multilingual evaluation, depending on checkpoint. |
| Qwen 3 ASR | Approx. 6-9 | Recent ASR model family with competitive benchmark results; exact WER depends on model variant and evaluation setup. |

Live benchmark source: https://huggingface.co/datasets/hf-audio/open-asr-leaderboard

The Open ASR Leaderboard tracks benchmark performance across multiple speech-recognition datasets, including clean read speech, meetings, talks, earnings calls, and other real-world audio domains.

## Features

### 1. Privacy

- Runs fully locally by default.
- No audio is sent to external services during normal transcription.
- No audio is stored on disk unless explicitly configured; SpeakEasy captures microphone audio into memory, trims silence, transcribes it, and releases the buffer.
- The Granite model is downloaded to local storage and loaded from disk for inference.

#### Professional Mode

Professional Mode is optional. It sends the completed text transcript, not the raw audio, to an external text API using a user-provided API key.

Professional Mode can rewrite dictated text to make it clearer, more polished, or more intentionally styled. Built-in presets include professional workplace cleanup, technical communication, casual-friendly tone, email correspondence, simplified writing, Medieval Bard, Wise Galactic Sage, and Unhinged Mode. You can also create custom presets, preserve domain vocabulary, and choose the OpenAI model used for cleanup.

Use cases include removing filler words, neutralizing passive-aggressive language, improving grammar and punctuation, turning rough dictation into professional correspondence, or applying a creative voice. External API usage only happens when Professional Mode is enabled and configured with an API key. API keys can be kept in Windows Credential Manager.

### 2. Multilingual Capabilities

- Supports multilingual speech input for English, French, German, Spanish, Portuguese, and Japanese, plus automatic language selection.
- Supports transcription and speech translation in one Granite pipeline.
- Translation output targets include English, French, German, Spanish, Japanese, Italian, and Mandarin.
- Example: speak Spanish and output English text when translation mode targets English.

Common use cases include multilingual dictation, translating spoken notes into a working language, and capturing speech from meetings or source material where the spoken language differs from the desired written output.

### Other Capabilities

- Global Windows hotkeys for record/stop, quit, and Developer Panel toggle.
- Auto-copy and optional auto-paste into the currently focused application.
- GPU and CPU build variants. GPU mode uses CUDA when available; CPU mode runs without NVIDIA hardware but is slower.
- Keyword biasing for names, acronyms, jargon, product terms, and other vocabulary the model should prefer.
- Prompt-controlled punctuation, capitalization, plain text mode, sentence case, and spoken-word preservation.
- In-memory transcription history with copy actions and original-vs-cleaned comparison for Professional Mode.
- Developer Panel with settings, advanced tuning, realtime RAM/VRAM/GPU metrics, ASR throughput, LLM token throughput, logs, Professional Mode configuration, and history.
- Local model downloader and installer scripts for GPU and CPU distributions.
- Single-instance guard so duplicate desktop instances do not compete for hotkeys, audio, or model memory.

## Architecture & Processing Flow

```text
Default local path

Audio Input
  microphone / selected device
        |
        v
Preprocessing
  in-memory float32 mono audio
  silence trimming
  resample to 16 kHz
        |
        v
Transcription Engine
  IBM Granite Speech 4.1 2B
  local PyTorch / Transformers inference
        |
        v
Post-Processing
  chunk stitching for long recordings
  prompt-controlled punctuation / formatting
        |
        v
Output
  history -> clipboard -> optional Ctrl+V paste


Optional Professional Mode path

Local transcript
        |
        v
Professional Mode preset
  custom instructions / tone / grammar / vocabulary
        |
        v
External text API
  user-provided API key
  transcript text only
        |
        v
Cleaned output
  history -> clipboard -> optional Ctrl+V paste
```

Audio input comes from the selected microphone through a persistent PortAudio stream. When recording stops, SpeakEasy gathers the captured frames from memory and rejects empty or silent recordings.

Preprocessing converts audio to a contiguous mono `float32` buffer, trims leading and trailing silence, and guarantees the engine receives 16 kHz audio. Long recordings are split into overlapping chunks when required by the model and stitched back into one final transcript.

The transcription engine is IBM Granite Speech 4.1 2B running locally through PyTorch and Transformers. Granite prompt options control transcription vs translation, punctuation, formatting style, target translation language, and keyword biasing.

Post-processing keeps the user-facing result as one final text string. Clipboard writes and paste simulation run from the main Qt thread after transcription completes.

Professional Mode is a separate optional text-cleanup stage after local transcription. It sends transcript text to an external API only when the user enables Professional Mode and provides an API key.

### Local Mode

Local Mode is the default behavior. Audio capture, preprocessing, Granite inference, chunk stitching, history, clipboard copy, and optional paste all run on the local Windows machine.

### Professional Mode

Professional Mode keeps transcription local, then optionally sends the completed transcript text to an external API for rewriting. Raw audio is not sent through this path. If the API call fails or times out, SpeakEasy falls back to the original local transcript.

## Requirements

| Requirement | Details |
| --- | --- |
| OS | Windows 10/11 64-bit |
| Python | 3.11+ for source installs |
| Package manager | `uv` |
| Disk space | About 5 GB for the Granite model plus application files |
| GPU mode | NVIDIA GPU, 6 GB VRAM minimum, 8 GB recommended |
| CPU mode | 8 GB RAM minimum, 16 GB recommended; inference is slower |

## Install From Source

```powershell
uv sync --extra dev
uv run python -m speakeasy download-model --target-dir dev-temp\models
.\installer\Build-Installer.ps1 -Mode Source -Clean
```

Source mode stores mutable data under `dev-temp/` by setting `SPEAKEASY_HOME`.

## Run

Launch the app from source:

```powershell
uv run python -m speakeasy
```

Download the Granite model manually:

```powershell
uv run python -m speakeasy download-model --target-dir dev-temp\models
```

Print the installed version:

```powershell
uv run python -m speakeasy --version
```

## Build Installers

GPU build:

```powershell
.\installer\Build-Installer.ps1 -Mode Build
```

CPU build:

```powershell
.\installer\Build-Installer.ps1 -Mode Build -Variant CPU
```

Fast development build:

```powershell
.\installer\Build-Installer.ps1 -Mode Build -Fast
```

Installed paths:

| Path | Default location |
| --- | --- |
| Application | `C:\Program Files\SpeakEasy AI Granite` |
| Data | `%ProgramData%\SpeakEasy AI Granite` |
| Model | `%ProgramData%\SpeakEasy AI Granite\models\granite` |
| Settings | `%ProgramData%\SpeakEasy AI Granite\config\settings.json` |
| Presets | `%ProgramData%\SpeakEasy AI Granite\config\presets` |
| Logs | `%LOCALAPPDATA%\SpeakEasy AI Granite\logs` |

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `engine` | `granite` | Speech engine. |
| `device` | `cuda` in GPU builds, `cpu` in CPU builds | Inference device. |
| `language` | `en` | Spoken language for ASR; `auto` is also available. |
| `speech_task` | `transcribe` | `transcribe` or `translate`. |
| `translation_target_language` | `English` | Target language for translation mode. |
| `keyword_bias` | Empty | Comma-separated names, acronyms, jargon, and product terms. |
| `punctuation` | `true` | Requests punctuation and capitalization in the Granite prompt. |
| `formatting_style` | `sentence_case` | `sentence_case`, `plain_text`, or `preserve_spoken_wording`. |
| `auto_copy` | `true` | Copy completed output to the clipboard. |
| `auto_paste` | `true` | Paste completed output into the active application after copy. |
| `hotkey_start` | `ctrl+alt+p` | Start/stop recording hotkey. |
| `hotkey_quit` | `ctrl+alt+q` | Quit hotkey. |
| `hotkey_dev_panel` | `ctrl+alt+d` | Developer Panel hotkey. |
| `professional_mode` | `false` | Enables optional external text cleanup after local transcription. |

Granite Speech behavior is prompt-driven. Punctuation, translation, formatting, and keyword bias are expressed in the chat prompt sent with `<|audio|>` rather than through Whisper-style decoder switches.

## Testing

Run the full test suite:

```powershell
uv run pytest tests/ -v
```

Focused Granite and model tests:

```powershell
uv run pytest tests/test_granite_transcribe.py tests/test_model_downloader.py tests/test_model_presence.py -v
```

The tests mock Qt and GPU dependencies where practical, so they do not require a display or an NVIDIA GPU for normal CI-style validation.

## Technical Notes

- Engine load, transcription, and unload run on a dedicated Python-managed worker pool to avoid CUDA hangs seen with Qt thread pools on Windows.
- Clipboard writes run on the main Qt thread.
- All engines receive 1D mono `float32` audio resampled to 16 kHz.
- Long recordings are chunked internally and returned to the UI as one stitched final result.
- Granite prompts include `<|audio|>` and use the tokenizer chat template.
- The GPU build can monitor RAM, VRAM, GPU name, temperature, ASR throughput, and token generation rates in the Developer Panel.
- The CPU build restricts device selection to CPU and omits CUDA-specific runtime behavior.

## Priority Checklist for Transcription Users

1. Accuracy: Granite Speech 4.1 2B is the main reason to use this app; it is currently a leaderboard-leading ASR model.
2. Local privacy: default transcription does not send audio or text to an external service.
3. Workflow speed: global hotkey, auto-copy, and auto-paste make dictation usable in any Windows application.
4. Multilingual support: transcription and translation share one local speech pipeline.
5. Professional Mode control: external rewriting is opt-in, preset-driven, and limited to transcript text.
6. Developer visibility: realtime metrics, logs, history, and validation tools make the app easier to diagnose and tune.
7. Deployment flexibility: GPU and CPU installers support high-performance desktops and non-NVIDIA machines.

## Repository Status

This repository is the Granite fork of SpeakEasy AI. The original Cohere-based repository remains separate and unchanged.

## License

The application is MIT licensed. IBM Granite Speech is provided under its own Apache 2.0 model license on Hugging Face.