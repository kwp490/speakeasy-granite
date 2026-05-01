# Copilot Instructions — SpeakEasy AI

## Project overview

Windows-only desktop speech-to-text application. Python 3.11+, PySide6 (Qt6),
HuggingFace Transformers (IBM Granite Speech engine), PyInstaller frozen builds, Inno
Setup installer. Two build variants: GPU (CUDA via torch+cu128) and CPU.

Package manager: **uv** (not pip). All commands use `uv run` / `uv sync`.
Use the existing uv-managed project environment for Python commands; do not
invoke VS Code/Pylance Python environment setup tools unless the task specifically
requires interpreter metadata or switching interpreters. If `uv run ...` triggers
environment creation/update, report that as uv behavior rather than repeatedly
configuring a separate Python environment.

## Directory map

```
speakeasy/               # Application source package
  __main__.py           # Entry point, single-instance mutex, CLI (download-model, --version)
  main_window.py        # PySide6 QMainWindow — UI, engine lifecycle, audio, clipboard, hotkeys
  config.py             # Settings dataclass, JSON persistence, path constants (INSTALL_DIR)
  audio.py              # Mic recording (sounddevice), WAV capture
  clipboard.py          # Win32 clipboard read/write (main-thread only)
  hotkeys.py            # Global hotkey registration (keyboard lib), sleep/wake re-register
  workers.py            # Worker/QRunnable + DedicatedWorkerPool (Python-thread facade)
  text_processor.py     # Professional Mode — OpenAI API text cleanup
  pro_preset.py         # ProPreset dataclass, built-in + user JSON presets
  settings_dialog.py    # Settings UI dialog
  pro_settings_dialog.py# Professional Mode settings UI
  gpu_monitor.py        # nvidia-ml-py VRAM/utilization polling
  _resource_monitor.py  # System resource monitoring
  _constants.py         # UI colors, timer intervals, Win32 message IDs
  _build_variant.py     # GPU vs CPU variant flag for frozen builds
  model_downloader.py   # HuggingFace Hub model download logic
  engine/
    __init__.py         # Engine registry (ENGINES dict, availability check)
    base.py             # ABC SpeechEngine — load/transcribe/unload interface
    granite_transcribe.py# GraniteTranscribeEngine implementation
    audio_utils.py      # Resampling (ensure_16khz), audio preprocessing
installer/
  Build-Installer.ps1   # Build/install/source-run tool (modes: Build, Release, Source, Install)
  Install-SpeakEasy-Source.ps1 # Automated source install (admin); supports -Variant GPU|CPU
  granite-model-setup.ps1# HF model download helper invoked by Inno Setup post-install
  speakeasy-setup.iss    # Inno Setup script (GPU)
  speakeasy-cpu-setup.iss# Inno Setup script (CPU)
tests/                  # pytest suite
dev-temp/               # Ephemeral local dev data (gitignored)
```

## Build & test commands

```powershell
uv sync --extra dev                                      # Install all deps
uv run pytest tests/ -v                                  # Run test suite
uv run python -m speakeasy                                # Run from source (needs SPEAKEASY_HOME)
.\installer\Build-Installer.ps1 -Mode Source             # Run from source (sets up dev-temp)
.\installer\Build-Installer.ps1 -Mode Source -Clean      # Reset dev-temp, run from source
.\installer\Build-Installer.ps1 -Mode Build              # PyInstaller + Inno Setup (GPU)
.\installer\Build-Installer.ps1 -Mode Build -Variant CPU # CPU variant
.\installer\Build-Installer.ps1 -Mode Build -Fast        # Dev build (fast compression)
.\installer\Build-Installer.ps1 -Mode Release            # Full release cycle (requires admin)
.\installer\Build-Installer.ps1 -Mode Install            # Silent-install latest build (requires admin)
```

## Architecture rules

### Threading
- **Clipboard writes** (`set_clipboard_text`) must only happen on the **main Qt thread**. Workers emit signals; connected slots run on the main thread.
- **Engine load/transcribe/unload** must run on **Python-managed threads** (DedicatedWorkerPool), NOT QThreadPool. QThreadPool can hang with CUDA speech models on Windows.
- Generic background tasks use `Worker(QRunnable)` via `QThreadPool`.

### Audio pipeline
- All engines receive **1D float32 mono numpy arrays** resampled to **16 kHz**.
- Recording sample rate may differ; `ensure_16khz()` handles conversion.

### Engine pattern
- Single engine registry in `engine/__init__.py` — currently only `"granite"`.
- Availability gated on both importability AND model files on disk (`config.json` present).
- `unload()` must: `del` model → `gc.collect()` → `torch.cuda.empty_cache()`.

### Granite engine gotchas
- Granite prompts must include `<|audio|>` and be formatted with the tokenizer chat template.
- Decode only tokens generated after the prompt input IDs.
- Cast floating processor outputs to model dtype before `generate()`.
- Use Python threads, never QThreadPool.

### Streaming partials (live-draft transcription)
- Long recordings are chunked inside `GraniteTranscribeEngine._transcribe_impl`. When the
  caller passes `partial_callback=<fn>`, the engine invokes it after each chunk with
  `(running_stitched_text, chunk_index_1based, total_chunks)` and **swallows any exception**
  the callback raises (logged, never propagated). Single-chunk audio does NOT fire the callback.
- `WorkerSignals.partial = Signal(str, int, int)` carries the callback payload from the
  engine thread to the UI. Always connect with `Qt.QueuedConnection` so the slot runs on
  the main Qt thread.
- `MainWindow` keeps exactly one `_active_draft_entry: Optional[_HistoryEntry]`. The
  partial slot creates it on the first partial and updates it in place thereafter;
  `_add_history` auto-finalizes it (via `_HistoryEntry.mark_final`) when the authoritative
  result lands so there is never a stale orphan draft row. Clipboard writes and auto-paste
  are gated on the final-result path **only** — they never fire per chunk.
- Partials are disabled when `settings.streaming_partials_enabled` is False (Settings
  dialog checkbox; default True). Behavior then matches the pre-streaming flow.
- `DedicatedWorkerPool` remains single-worker. Do not make the engine pool concurrent.

### Security
- **OpenAI API key** is stored in Windows **keyring** (not settings.json). Never log, print, or serialize `_api_key` to disk.
- Use `_sanitize_error()` from `text_processor.py` when surfacing API errors.

### Config
- `INSTALL_DIR` = `SPEAKEASY_HOME` env var (default: `C:\Program Files\SpeakEasy AI Granite`).
- Source mode uses `dev-temp/` via `SPEAKEASY_HOME=dev-temp`.
- Settings file: `config/settings.json`. User presets: `config/presets/*.json`.
- Five built-in presets are always available and cannot be deleted.

### Sleep/wake
- `HotkeyManager.re_register()` is called on `WM_POWERBROADCAST` / `PBT_APMRESUMEAUTOMATIC` to restore keyboard hooks.

### Single-instance
- Win32 named mutex `Global\SpeakEasyAIGraniteMutex` prevents duplicate processes.

### Build variants
- **GPU**: `speakeasy.spec` + `speakeasy-setup.iss` (CUDA, includes torchaudio)
- **CPU**: `speakeasy-cpu.spec` + `speakeasy-cpu-setup.iss` (no CUDA, smaller)
- `_build_variant.py` contains `VARIANT = "gpu"` by default. The CPU spec patches it to `"cpu"` at build time (and restores it after). `Install-SpeakEasy-Source.ps1 -Variant CPU` also patches it for source installs.
- At runtime, `config.py`, `gpu_monitor.py`, and `settings_dialog.py` branch on `VARIANT` to set device defaults, skip GPU metrics, and restrict the device dropdown.
- Both installer variants share the same Inno Setup `AppId` — installing one replaces the other.
- torch and torchaudio versions **must match** (same CUDA/CPU index in pyproject.toml)
- CPU spec uses **two** strip-pattern lists: `_STRIP_PATTERNS` (applied to `a.pure`, `a.binaries`, `a.datas`) and `_CUDA_BINARY_PATTERNS` (applied **only** to `a.binaries`). CUDA patterns like `cudnn` match Python module names (e.g. `torch.backends.cudnn`) — applying them to `a.pure` breaks the frozen build.

## Test conventions

- Tests mock Qt and GPU dependencies; no GPU or display required.
- `test_frozen_compat.py` validates the PyInstaller `dist/` bundle structure.
- Run with `uv run pytest tests/ -v`.

## Code style

- Type hints where practical.
- Import order: stdlib → third-party → local.
- Follow existing patterns — don't over-engineer or add abstractions for one-off operations.
