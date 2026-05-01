# Contributing to SpeakEasy AI

## Dev Setup

```bash
# Clone and install all dependencies (including dev tools)
git clone https://github.com/kwp490/SpeakEasyAI.git
cd SpeakEasyAI
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

## Code Style

- Use type hints where practical
- Follow existing patterns in the codebase
- Keep imports sorted (stdlib → third-party → local)

## Architecture Notes

- **Thread safety**: Clipboard writes (`set_clipboard_text`) must only happen on the main Qt thread. Worker threads emit signals; connected slots run on the main thread.
- **Audio format**: All engine calls receive 1D float32 mono numpy arrays. Audio is resampled to 16 kHz before engine input, regardless of recording sample rate.
- **Single process**: The Cohere engine runs in-process via HuggingFace `transformers`. No subprocess bridge needed.
- **GPU cleanup**: `unload()` methods must explicitly `del` the model, call `gc.collect()`, and `torch.cuda.empty_cache()` to free VRAM.
- **Professional Mode**: Text cleanup runs on a `Worker` thread via the OpenAI API (no GPU conflict). The API key is held in memory on `MainWindow._api_key` — it must **never** be logged, printed, or serialized to `settings.json`. Use `_sanitize_error()` from `text_processor.py` when handling API exceptions.
- **Preset system**: Professional Mode uses `ProPreset` dataclass instances. Five built-in presets are always available; user presets are stored as JSON files in `config/presets/`. Built-in presets cannot be deleted.
- **Sleep/wake recovery**: `HotkeyManager.re_register()` is called on `WM_POWERBROADCAST` / `PBT_APMRESUMEAUTOMATIC` to restore keyboard hooks invalidated during sleep.
- **Single-instance guard**: A Windows named mutex (`Global\SpeakEasyAIMutex`) prevents multiple processes.

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
# Output: installer/Output/SpeakEasy-AI-Setup-0.7.1.exe
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

Please use the [GitHub Issues](https://github.com/kwp490/SpeakEasyAI/issues) page. Include:

- SpeakEasy AI version
- Windows version
- GPU model and driver version
- Steps to reproduce
- Relevant log output from `logs/speakeasy.log`
