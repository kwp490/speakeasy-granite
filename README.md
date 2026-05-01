# SpeakEasy AI Granite

Native Windows speech-to-text and speech translation powered by IBM Granite Speech 4.1 2B.

SpeakEasy AI Granite is a Windows desktop dictation app built with Python, PySide6, HuggingFace Transformers, and PyTorch. It records microphone audio locally, runs the IBM Granite Speech model on GPU or CPU, and can copy or paste the final text into whatever application you are using.

## Model

This fork uses [ibm-granite/granite-speech-4.1-2b](https://huggingface.co/ibm-granite/granite-speech-4.1-2b).

- Model family: IBM Granite Speech
- License: Apache 2.0 for the model
- Primary tasks: automatic speech recognition, speech translation, keyword-biased ASR
- ASR languages: English, French, German, Spanish, Portuguese, Japanese
- Translation targets exposed by the app: English, French, German, Spanish, Portuguese, Japanese, Italian, Mandarin

The model is downloaded from Hugging Face into the app's local model directory. A Hugging Face token is optional unless the Hub rejects anonymous access for your account or network context.

## Requirements

- Windows 10/11 64-bit
- Python 3.11+
- `uv` package manager
- NVIDIA GPU recommended for usable performance
- CPU mode is available but may be slow for a 2B speech-language model

## Install From Source

```powershell
uv sync --extra dev
uv run python -m speakeasy download-model --target-dir dev-temp\models
.\installer\Build-Installer.ps1 -Mode Source -Clean
```

Source mode stores mutable data under `dev-temp/` by setting `SPEAKEASY_HOME`.

## Run Tests

```powershell
uv run pytest tests/ -v
```

Focused Granite engine tests:

```powershell
uv run pytest tests/test_granite_transcribe.py tests/test_engine_load.py tests/test_model_downloader.py -v
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

The Granite fork uses a separate app identity from the Cohere app:

- Install directory: `C:\Program Files\SpeakEasy AI Granite`
- Data directory: `%ProgramData%\SpeakEasy AI Granite`
- Log directory: `%LOCALAPPDATA%\SpeakEasy AI Granite\logs`
- Model directory: `%ProgramData%\SpeakEasy AI Granite\models\granite`

## Settings

Key settings live in `config/settings.json`:

| Setting | Default | Purpose |
| --- | --- | --- |
| `engine` | `granite` | Speech engine |
| `device` | `cuda` in GPU builds, `cpu` in CPU builds | Inference device |
| `language` | `en` | Spoken language for ASR |
| `speech_task` | `transcribe` | `transcribe` or `translate` |
| `translation_target_language` | `English` | Target language for translation mode |
| `keyword_bias` | empty | Optional comma-separated bias words |
| `punctuation` | `true` | Requests punctuation/capitalization in the Granite prompt |

## Architecture Notes

- Engine load/transcribe/unload runs on `DedicatedWorkerPool`, not `QThreadPool`.
- Clipboard writes stay on the main Qt thread.
- Engines receive mono float32 audio resampled to 16 kHz.
- Long recordings are chunked and stitched; partial callbacks update the live draft history row.
- Granite prompts are built with `<|audio|>` and the tokenizer chat template.

## Repository Status

This repository is the Granite fork of SpeakEasy AI. The original Cohere-based repository remains separate and unchanged.

## License

The application is MIT licensed. IBM Granite Speech is provided under its own Apache 2.0 model license on Hugging Face.