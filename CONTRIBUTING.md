# Contributing to SpeakEasy AI

## Dev Setup

```bash
# Clone and install all dependencies (including dev tools)
git clone https://github.com/kwp490/speakeasy-granite.git
cd speakeasy-granite
uv sync --extra dev
```

## Running Tests

```bash
uv run pytest
```

## Compile Check

```bash
uv run python -m compileall speakeasy
```

## Verify Engine Availability

```bash
uv run python -c "from speakeasy.engine import ENGINES; print(list(ENGINES.keys()))"
```

## Test Suite

The suite is built around the **parametrized conformance spine**
([tests/test_contract_conformance.py](tests/test_contract_conformance.py)): every
`TranscriptionService` implementation (the in-process adapter, the remote client,
and the `FakeEngine` double) is driven through the same `TranscriptionOptions`
cases, so behavior stays identical across transports.

Run the whole suite in parallel:

```bash
uv run pytest -n auto
```

### Layering rules

`core/`, `services/`, and `engines/` must stay import-light so the UI and the
remote client can load without pulling in the ML stack. **No module-scope import
of `torch`, `transformers`, `librosa`, `accelerate`, or `PySide6`** is allowed in
those packages — heavy imports live inside functions or behind the engine
boundary. This keeps cold-start fast and lets a frozen build defer the ML import
until a real model is loaded.

This rule is enforced automatically:

```bash
# Fails if a forbidden module is imported at module scope in core/services/engines
uv run pytest tests/test_ml_import_isolation.py
# Frozen-build import isolation (PyInstaller layout):
uv run pytest tests/test_frozen_ml_isolation.py
```

### Driving engines in tests with FakeEngine

Use [`FakeEngine`](speakeasy/engines/fake.py) for all UI, controller, and
service-level tests — it is a deterministic `SpeechEngine` double with no model
download or GPU dependency. Drive transcription through the public contract
rather than engine internals: wrap the engine in `InProcessEngineService` and
pass a `TranscriptionOptions`, instead of calling private engine methods or the
`configure_prompt_options` side-channel directly.

```python
from speakeasy.core.contract import TranscriptionOptions
from speakeasy.core.model_source import LocalDirSource
from speakeasy.services.inprocess import InProcessEngineService
from speakeasy.engines.fake import FakeEngine

service = InProcessEngineService(FakeEngine(transcript="hello world"))
service.load(LocalDirSource(path="/dummy"), "cpu")
result = service.transcribe(audio, TranscriptionOptions(task="transcribe"))
```

### Nightly real-model regression job

The fast suite never loads the real Granite weights. A separate **nightly
real-model regression job** runs out of CI band against the downloaded model to
guard transcription quality:

- **Scope:** loads the real Granite engine on both **GPU and CPU**, transcribes
  the committed fixtures in [tests/fixtures/audio/](tests/fixtures/audio/), and
  compares the output against the reference transcripts in that fixture set.
- **Gate:** the measured Word Error Rate (WER) must stay at or below the
  committed baseline; a regression fails the job and **gates merges that touch
  the engine layer** (`speakeasy/engine/`).
- **Why nightly:** loading the model and running full inference is too slow and
  hardware-dependent for per-PR CI, so it runs on a schedule rather than on every
  push.

To reproduce the nightly check locally with a downloaded model:

```bash
# Requires the Granite model present locally and a GPU for the GPU pass.
uv run python tools/bench.py --device cuda    # GPU pass: latency + WER vs references
uv run python tools/bench.py --device cpu     # CPU pass
uv run python tools/bench.py --smoke          # zero-dependency harness self-check (no model)
```

## Code Style

- Use type hints where practical
- Follow existing patterns in the codebase
- Keep imports sorted (stdlib → third-party → local)

## Architecture Notes

- **Thread safety**: Clipboard writes (`set_clipboard_text`) must only happen on the main Qt thread. Worker threads emit signals; connected slots run on the main thread.
- **Audio format**: All engine calls receive 1D float32 mono numpy arrays. Audio is resampled to 16 kHz before engine input, regardless of recording sample rate.
- **Single process**: The Granite engine runs in-process via HuggingFace `transformers`. No subprocess bridge needed.
- **GPU cleanup**: `unload()` methods must explicitly `del` the model, call `gc.collect()`, and `torch.cuda.empty_cache()` to free VRAM.
- **Professional Mode**: Text cleanup runs on a `Worker` thread via the OpenAI API (no GPU conflict). The API key is held in memory on `MainWindow._api_key` — it must **never** be logged, printed, or serialized to `settings.json`. Use `_sanitize_error()` from `text_processor.py` when handling API exceptions.
- **Preset system**: Professional Mode uses `ProPreset` dataclass instances. Five built-in presets are always available; user presets are stored as JSON files in `config/presets/`. Built-in presets cannot be deleted.
- **Sleep/wake recovery**: `HotkeyManager.re_register()` is called on `WM_POWERBROADCAST` / `PBT_APMRESUMEAUTOMATIC` to restore keyboard hooks invalidated during sleep.
- **Single-instance guard**: A Windows named mutex (`Global\SpeakEasyAIGraniteMutex`) prevents multiple processes.

## Building the Binary

```bash
uv sync --extra dev
uv run pyinstaller speakeasy.spec
```

## Building the Installer

After building the binary, compile the Inno Setup installer:

```bash
# Requires Inno Setup 6.x — https://jrsoftware.org/isdl.php
iscc installer\speakeasy-setup.iss
# Output: installer/Output/SpeakEasy-AI-Granite-Setup-<version>.exe
```

Or run the combined build script:

```powershell
.\installer\Build-Installer.ps1
```

### Build Performance (Optional)

Install [AIM Toolkit](https://sourceforge.net/projects/aim-toolkit/) to enable automatic RAM disk acceleration. The build script will auto-provision a 10 GB NTFS RAM disk on `R:` via `aim_ll.exe` and redirect `build/` and `dist/` there using NTFS junctions. This cuts PyInstaller I/O latency dramatically on large builds.

AIM Toolkit supersedes ImDisk Toolkit, which has compatibility issues on recent Windows versions. If you already have a RAM disk mounted as `R:` (from any tool), the build script will detect and use it automatically.

## Creating a Release

See [RELEASE.md](RELEASE.md) for the full version-bump → tag → publish checklist.

## Filing Issues

Please use the [GitHub Issues](https://github.com/kwp490/speakeasy-granite/issues) page. Include:

- SpeakEasy AI version
- Windows version
- GPU model and driver version
- Steps to reproduce
- Relevant log output from `logs/speakeasy.log`
