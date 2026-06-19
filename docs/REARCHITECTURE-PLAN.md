# SpeakEasy AI Granite — Rearchitecture Plan

**Repository:** `kwp490/speakeasy-granite` @ `2a357a5` ("Link release checksums in README")
**Current version:** 0.14.5 · **Date of analysis:** 2026-06-11
**Status:** Plan only — no code changes. Every file/line reference below was verified against the repo at the commit above.

---

## 1. Executive Summary

SpeakEasy AI Granite is a well-built, single-package PySide6 Windows dictation app with a real (if thin) engine abstraction already in place (`speakeasy/engine/base.py` defines a `SpeechEngine` ABC). The biggest structural problem is not the absence of an abstraction — it is that **the abstraction leaks at import time and at the settings layer**:

1. `speakeasy/main_window.py:61` does a **top-level** `from .engine.granite_transcribe import GraniteTranscribeEngine`, and `granite_transcribe.py` has **module-level** `import torch` / `from transformers import ...`. Therefore the UI process cannot start without ~1.5 GB of ML packages importable, and PyInstaller must bundle them into both installers (GPU installer 1.87 GB, CPU 202 MB per README).
2. The engine reaches *back into the app* (`granite_transcribe.load()` imports `speakeasy.model_downloader` to auto-download), creating a UI↔engine↔downloader cycle.
3. `model_path` is a bare string assumed to be a **local parent directory containing a `granite/` subfolder**, and `Settings.validate()` (`config.py:147-149`) silently **resets it to default if the directory is unreachable** — which makes UNC/network paths that are temporarily offline destructive to user configuration.
4. Engine capabilities are duck-typed via `getattr(self._engine, "configure_prompt_options", None)` (`main_window.py:1196`) and `getattr(..., "actual_device", ...)`, so adding a second engine means re-auditing the 2,014-line `MainWindow`.

The plan below converts the existing ABC into a **formal, transport-agnostic engine contract** (`TranscriptionService`), enforces a **"UI never imports torch/transformers"** rule with tests, introduces a **discriminated `model_source` settings schema** (managed / local dir / UNC / remote HTTP endpoint), and ships a small **`speakeasy-server` mode** so "model on another computer" becomes a remote inference endpoint rather than a fragile network filesystem hack — while keeping local, private dictation the unchanged default.

Recommended posture: **incremental migration, no rewrite.** The in-process engine stays the default through every phase; the remote client and process isolation are additive. The single highest-leverage early win is **Phase 2 (lazy engine boundary)** plus two dependency cuts that need no architecture change at all: replacing `librosa` (used only for one `resample` call in `engine/audio_utils.py:21-23`) with `soxr`, and removing `accelerate`/`torchaudio` if validation confirms they are unneeded (neither is referenced in app code; see §7).

Target version for this body of work: **0.15.0** (minor bump — new features, schema migration, no breaking CLI changes), with intermediate `0.15.0-rc` builds per phase.

---

## 2. Current Repository Inventory

97 files total (excluding `.git`). Python LOC: ~16,350 across `speakeasy/` + `tests/`.

### 2.1 Top-level layout

| Path | Contents |
| --- | --- |
| `speakeasy/` | Application package (≈9,500 LOC) |
| `speakeasy/engine/` | Engine subpackage: `base.py`, `granite_transcribe.py`, `audio_utils.py`, `__init__.py` |
| `speakeasy/assets/` | `app.ico`, 11 SVG icons, `validation.wav` |
| `tests/` | 27 test modules + `conftest.py`, **572 test functions** |
| `installer/` | `Build-Installer.ps1`, `Install-SpeakEasy-Source.ps1`, `granite-model-setup.ps1`, `speakeasy-setup.iss`, `speakeasy-cpu-setup.iss` |
| `hooks/` | `hook-transformers.py` (PyInstaller hook: copies transformers dep metadata, excludes legacy model families, `module_collection_mode='pyz'`) |
| `speakeasy.spec` / `speakeasy-cpu.spec` | GPU and CPU PyInstaller specs; CPU spec live-patches `_build_variant.py` to `VARIANT = "cpu"` during Analysis |
| `docs/images/` | Two UI screenshots |
| `pyproject.toml`, `uv.lock` | hatchling build; uv-managed, pinned to `win32/AMD64`; torch from `pytorch-cu128` index |
| `README.md`, `CHANGELOG.md`, `RELEASE.md`, `SECURITY.md`, `CONTRIBUTING.md`, `.github/RELEASE_NOTES.md` | Docs |

### 2.2 Main runtime modules

| Module | Lines | Role |
| --- | ---: | --- |
| `main_window.py` | 2,014 | God object: window UI, model lifecycle, dictation state machine, transcription orchestration, clipboard/paste, metrics forwarding, power-resume CUDA health probe (`:1969`), Granite setup prompts (`:1646-1770`) |
| `theme.py` | 826 | Colors, fonts, section/toggle factories |
| `developer_panel.py` | 792 | Snapped side window; 7 tabs: Settings, AI Providers, AI Writing Profiles, Metrics, Logs, History, Advanced |
| `model_downloader.py` | 769 | HF Hub download, `GRANITE_REQUIRED_FILES` manifest, `model_health()`/`model_ready()`, exit codes shared with the Inno installer, progress JSONL protocol, setup-script launcher |
| `settings_dialog.py` | 620 | `SettingsWidget` (user settings), `AdvancedSettingsWidget` (model path, inference timeout, segmentation, diagnostics), legacy `SettingsDialog` shim |
| `pro_mode_widget.py` / `pro_preset.py` / `ai_providers_widget.py` / `text_processor.py` | 414/401/272/318 | OpenAI-based AI Writing Profiles (cleanup of dictated text); keyring-held API key |
| `__main__.py` | 345 | Entry point: single-instance mutex, logging, CLI (`download-model`, `--version`), Qt lifecycle |
| `status_pills.py` | 336 | Status pill bar |
| `audio.py` | 278 | `AudioRecorder` (sounddevice InputStream, RMS silence gate, trim) |
| `config.py` | 230 | `Settings` dataclass (~35 fields), JSON persistence, legacy-key migration, `validate()` clamping |
| `hotkeys.py` | 193 | Win32 global hotkeys |
| `history_widget.py` | 176 | Transcription history tab |
| `workers.py` | 156 | `Worker(QRunnable)` + `DedicatedWorkerPool` (Python ThreadPoolExecutor facade; exists because CUDA DllMain thread-attach corrupts Qt-created threads — see its `warmup()` docstring) |
| `model_download_dialog.py` | 146 | Qt download progress dialog |
| `gpu_monitor.py` / `_resource_monitor.py` | 126/74 | pynvml + RAM polling |
| `clipboard.py` | 96 | Clipboard set + paste simulation |
| `_runtime_hook_dll.py` | ~50 | PyInstaller runtime hook: `_MEIPASS` DLL dirs, certifi `SSL_CERT_FILE`, torch/lib path |
| `_build_variant.py`, `_constants.py`, `app_identity.py` | small | Build flag, UI constants, icon path |

### 2.3 Engine subpackage

- `engine/base.py` (99 lines): `SpeechEngine` ABC — `name`, `vram_estimate_gb`, `load(model_path, device)`, `_transcribe_impl(audio_16k, language, punctuation, timeout)`, `unload()`, concrete `transcribe()` (resample + guards) and `_release_model()` (imports `accelerate.hooks` best-effort; `_cleanup_gpu_memory()` lazily imports torch).
- `engine/granite_transcribe.py` (320 lines): **module-level `import torch` and `from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor`**. Prompt construction (`_build_user_prompt`), chunked long-audio path via `chunk_audio`/`stitch_transcripts`, `MaxTimeCriteria` timeout, token stats, `configure_prompt_options()` side-channel, `load()` auto-downloads via `speakeasy.model_downloader`.
- `engine/audio_utils.py` (116 lines): `ensure_16khz()` — lazy `import librosa` for one `librosa.resample` call; `chunk_audio()`, `stitch_transcripts()` (word-overlap dedup).
- `engine/__init__.py`: `ENGINES` dict built by try-importing `granite_transcribe` (so merely importing the registry imports torch when available); `get_available_engines()` checks model files via `model_downloader.model_ready`.

### 2.4 Tests (572 functions, 27 files)

Largest: `test_main_window_layout.py` (61), `test_frozen_compat.py` (47 — AST/spec checks that **assert torch/transformers/librosa are in hiddenimports**, i.e. tests that encode the coupling), `test_professional_mode.py` (39), `test_build_naming.py` (38 — version consistency across `__init__.py`/pyproject/iss, torch↔torchaudio version-pairing asserts), `test_developer_panel_live.py` (37), `test_model_downloader.py` (33). `conftest.py` forces `QT_QPA_PLATFORM=offscreen`, `CUDA_VISIBLE_DEVICES=""`, custom `tmp_path`.

### 2.5 Dependency footprint (from `pyproject.toml`)

Runtime: PySide6, sounddevice, soundfile, numpy, nvidia-ml-py (win32), openai, keyring, **transformers ≥5.4, accelerate, torch ≥2.1 (cu128 index), torchaudio, huggingface-hub, hf_xet, sentencepiece, protobuf, librosa, safetensors**, urllib3. Dev: pyinstaller, pytest + plugins, pip-audit.

**Observed-usage audit of the heavy deps (verified by grep):**

| Package | Actual references in `speakeasy/` |
| --- | --- |
| torch | `engine/granite_transcribe.py` (module-level), `engine/base.py` (lazy, cleanup), `main_window.py:1969` (lazy, CUDA resume probe) |
| transformers | `engine/granite_transcribe.py` only |
| librosa | `engine/audio_utils.py:21-23` only (**one resample call**) |
| accelerate | `engine/base.py:79` lazy unload hook only; (`device_map=` in `from_pretrained` is the implicit consumer) |
| torchaudio | **Zero direct references.** Presumed transitively required by the Granite `AutoProcessor` feature extractor — *open question OQ-1, must be verified before removal* |
| sentencepiece/protobuf/safetensors/hf_xet | Tokenizer/weights/download plumbing — required while transformers is the runtime |


---

## 3. Current Architecture Map

```
┌──────────────────────────── UI process (speakeasy.exe) ────────────────────────────┐
│ __main__.py ── mutex, logging, CLI, QApplication                                   │
│   └─ MainWindow (main_window.py, 2014 LOC)                                         │
│        ├─ AudioRecorder (audio.py, sounddevice @ settings.sample_rate)             │
│        ├─ GraniteTranscribeEngine  ◄── constructed directly at :275                │
│        │     module-level: import torch, transformers          (≈1.5 GB deps)      │
│        │     load() ──► speakeasy.model_downloader (auto-download, HF Hub)         │
│        ├─ DedicatedWorkerPool (workers.py)  — Python threads, CUDA DllMain dodge   │
│        ├─ Worker(QRunnable) → trim_silence → engine.transcribe (in-process)        │
│        ├─ clipboard.py (main thread) → simulate_paste (worker)                     │
│        ├─ TextProcessor (OpenAI, optional, keyring)                                │
│        ├─ DeveloperPanel (7 tabs) ── SettingsWidget / AdvancedSettingsWidget       │
│        │                              └─ model_path QLineEdit + Browse (:448-455)  │
│        ├─ ResourceMonitor / gpu_monitor (pynvml)                                   │
│        └─ HotkeyManager (Win32)                                                    │
│ Settings (config.py) ── settings.json under %ProgramData% (or SPEAKEASY_HOME)      │
│ Model files ── %ProgramData%\SpeakEasy AI Granite\models\granite\                  │
└─────────────────────────────────────────────────────────────────────────────────────┘
Packaging: speakeasy.spec / speakeasy-cpu.spec → PyInstaller onedir → Inno Setup
           granite-model-setup.ps1 (elevated model download for frozen installs)
```

**Threading model:** UI on the Qt main thread; engine load/transcribe on `DedicatedWorkerPool` (a 1-thread `ThreadPoolExecutor` with a `warmup()` that must run **before** torch import — `workers.py:140-152` documents the CUDA `DllMain(DLL_THREAD_ATTACH)` stack-corruption hazard). Clipboard writes deliberately on the main thread (`main_window.py:1273`); paste simulation on a worker. AI cleanup on the general `QThreadPool` with a 20 s fallback `QTimer`.

**Model presence/download:** `model_downloader.model_ready()` / `model_health()` check `GRANITE_REQUIRED_FILES` + JSON validity + safetensors index references. Frozen builds launch `granite-model-setup.ps1` via ShellExecute (elevation); source builds download in-process with a Qt dialog. Exit codes (`EXIT_AUTH_REQUIRED=2`) are shared with `speakeasy-setup.iss`.

---

## 4. Major Coupling Problems

| # | Problem | Evidence | Consequence |
| --- | --- | --- | --- |
| C-1 | UI imports torch/transformers at module import time | `main_window.py:61` → `granite_transcribe.py:16-21` (module-level imports); also `engine/__init__.py` registry try-import | UI process cannot exist without full ML stack; PyInstaller must bundle it; startup pays import cost; CPU installer still ships torch |
| C-2 | Engine reaches back into app for downloads | `granite_transcribe.load()` imports `speakeasy.model_downloader` | Circular layering; engine untestable without app package; download policy hardcoded into inference path |
| C-3 | Capabilities are duck-typed | `getattr(self._engine, "configure_prompt_options", None)` (`main_window.py:1196`), `getattr(..., "actual_device", ...)` (`:910`), `token_stats` polling | Adding engine #2 requires auditing MainWindow; no machine-readable capability surface for UI (languages list `GRANITE_LANGUAGES` is hardcoded in `settings_dialog.py:43-51`) |
| C-4 | `model_path` is a bare local-dir string with destructive validation | `config.py:147-149` resets nonexistent paths to default at every load | UNC share offline at boot ⇒ user setting silently erased; no notion of remote endpoints |
| C-5 | Engine state side-channel | `configure_prompt_options()` mutates engine state before each `transcribe()` | Not thread-safe across requests; options not part of the transcribe contract |
| C-6 | Threading workaround is load-bearing | `DedicatedWorkerPool.warmup()` ordering requirement | Fragile invariant ("warm up before torch import") enforced only by code order in MainWindow init |
| C-7 | Tests encode the coupling | `test_frozen_compat.py:249-274` asserts torch/transformers/librosa in hiddenimports; `test_build_naming.py:367-388` asserts torch↔torchaudio pairing | Dependency reduction will *fail tests by design*; audit must rewrite these alongside the change |
| C-8 | librosa imported for one resample | `engine/audio_utils.py:21` | Pulls numba/llvmlite/scipy chain (~200–300 MB installed) into both bundles for a single function |
| C-9 | Resample location | `SpeechEngine.transcribe()` resamples on the engine side | When the engine moves remote, raw audio at arbitrary sample rate would cross the wire; resample should move client-side (it's cheap) so the wire format is fixed 16 kHz mono float32/WAV |
| C-10 | Version in 4+ places | `pyproject.toml:10`, `speakeasy/__init__.py:3`, both `.iss` files (`#define MyAppVersion`), README download links/table | Manual sync, guarded only by `test_build_naming.py` |


---

## 5. Target Architecture

### 5.1 Layered package layout (same repo, same wheel — no monorepo split yet)

```
speakeasy/
  core/                    # NEW — zero ML imports, zero Qt imports
    contract.py            #   TranscriptionService protocol, dataclasses (Capabilities, Options, Result)
    model_source.py        #   ModelSource discriminated union + validation
    errors.py              #   EngineError taxonomy (ModelMissing, AuthRequired, Timeout, RemoteUnreachable…)
    resample.py            #   ensure_16khz via soxr (moved from engine/audio_utils)
  engines/                 # RENAMED from engine/ — heavy imports allowed *inside functions only*
    registry.py            #   name → factory + EngineDescriptor; NO import of engine modules at module scope
    granite/engine.py      #   GraniteTranscribeEngine (torch/transformers imported inside load())
    fake.py                #   FakeEngine — deterministic test double, ships in package (used by --selftest)
  services/                # NEW
    inprocess.py           #   InProcessEngineService(TranscriptionService) wraps a SpeechEngine
    remote_client.py       #   RemoteEngineClient(TranscriptionService) — HTTP, stdlib/urllib3 only
    server.py              #   `speakeasy serve` — minimal HTTP server exposing the same contract
    provisioning.py        #   download / health / repair (absorbs model_downloader policy; engine no longer downloads)
  ui/                      # gradual migration target for main_window/developer_panel/settings_dialog
```

The UI constructs a `TranscriptionService` via one factory: `services.create_service(settings) -> TranscriptionService`. MainWindow never touches `SpeechEngine`, torch, or transformers again.

### 5.2 Process placement decision

**Q: in-process, separate local worker process, or local/remote service?**

**Answer: all three behind one interface, phased — in-process remains the default.**

- **Phase 1–3:** in-process (`InProcessEngineService`), but with strict lazy imports so the UI *can* run without torch installed (degraded: remote-only or "model not configured" state). This alone fixes C-1/C-3/C-5 and unlocks the UI-only test profile.
- **Phase 4:** `RemoteEngineClient` + `speakeasy serve`. "Another computer" = run `speakeasy serve --bind 0.0.0.0:8765 --token …` there; the client is ~200 lines of urllib3/httpx-free stdlib HTTP.
- **Phase 5+ (optional, gated on benchmarks):** local out-of-process engine host = `speakeasy serve --bind 127.0.0.1:0` auto-spawned by the UI, reusing the *identical* remote client. Benefits: crash/VRAM isolation, eliminates the `DedicatedWorkerPool.warmup()` CUDA-DllMain hazard (C-6), and allows a future torch-free UI installer. Cost: process lifecycle management, ~50–150 ms RPC overhead per utterance (negligible vs. inference). Do **not** make it mandatory in this cycle — in-process is battle-tested and the warmup workaround already functions.

### 5.3 UI ↔ ASR interface (the cleanest boundary)

A `typing.Protocol` (structural, no ABC inheritance requirement) in `core/contract.py`:

```python
class TranscriptionService(Protocol):
    def descriptor(self) -> EngineDescriptor: ...          # name, version, remote: bool
    def capabilities(self) -> EngineCapabilities: ...      # see §6
    def load(self, source: ModelSource, device: str) -> LoadReport: ...
    def unload(self) -> None: ...
    @property
    def is_loaded(self) -> bool: ...
    def transcribe(self, audio_16k: np.ndarray, options: TranscriptionOptions) -> TranscriptionResult: ...
    def health(self) -> HealthReport: ...                  # local: file manifest; remote: GET /v1/health
    def stats(self) -> EngineStats: ...                    # replaces token_stats tuple
```

`TranscriptionOptions` absorbs the `configure_prompt_options` side-channel (C-5): `task`, `language`, `translation_target`, `keyword_bias`, `punctuation`, `formatting_style`, `timeout_s`. `TranscriptionResult` carries `text`, `audio_s`, `inference_s`, `tokens_generated`, `realtime_factor`, `device` — replacing the `token_stats` 5-tuple polled by `main_window.py`. Resampling moves to the caller (`core/resample.py`), fixing C-9: the contract takes 16 kHz mono float32 only.

---

## 6. Engine Boundary Design

### 6.1 Capability model

```python
@dataclass(frozen=True)
class EngineCapabilities:
    languages: tuple[str, ...]               # ("auto","en","fr","de","es","pt","ja") for Granite
    supports_translation: bool
    translation_targets: tuple[str, ...]
    supports_keyword_bias: bool
    supports_timestamps: bool                # False for Granite today
    supports_streaming: bool                 # False today; reserved
    formatting_styles: tuple[str, ...]
    devices: tuple[str, ...]                 # ("cuda","cpu") / ("cpu",)
    max_clip_seconds: float                  # from model config (granite: max_audio_clip_s)
    is_remote: bool
```

`settings_dialog.py` stops hardcoding `GRANITE_LANGUAGES` / `GRANITE_TRANSLATION_TARGETS` / `GRANITE_FORMATTING_STYLES` and populates combos from `service.capabilities()` once loaded (with the current constants as the pre-load fallback so the form renders before model load). `Settings._VALID_LANGUAGES` etc. remain as last-resort clamps but are generated from the same constants module to avoid drift.

### 6.2 Registry without imports

`engines/registry.py` maps `name -> EngineDescriptor(factory: Callable[[], SpeechEngine], requires: tuple[str,...])`, where `factory` performs the heavy import. `get_available_engines()` (currently in `engine/__init__.py`) splits into `installed_engines()` (importlib.util.find_spec checks, no import) and provisioning-side model-file checks. This is what lets `import speakeasy.engines` succeed in a torch-free interpreter.

### 6.3 Error taxonomy

`core/errors.py`: `ModelNotConfigured`, `ModelFilesMissing(missing, invalid)`, `ModelAuthRequired` (maps EXIT_AUTH_REQUIRED), `DeviceUnavailable`, `InferenceTimeout`, `RemoteUnreachable(url, cause)`, `RemoteAuthFailed`, `RemoteVersionMismatch`. MainWindow's error labels and the download dialog key off types, not string matching.

### 6.4 Download policy moves out of the engine (fixes C-2)

`GraniteTranscribeEngine.load()` lines 82-103 (the model-missing → `download_model()` branch) move to `services/provisioning.py::ensure_model(source) -> ModelHealth`. The UI calls `ensure_model` *before* `service.load()`; the engine raises `ModelFilesMissing` and never downloads. `model_downloader.py` is retained but becomes an implementation detail of provisioning; its installer-facing CLI (`download-model`, exit codes, JSONL progress) is preserved unchanged because `speakeasy-setup.iss` and `granite-model-setup.ps1` depend on it.

### 6.5 Wire protocol (remote + future local worker)

Plain HTTP/1.1 + JSON, versioned under `/v1`:

| Endpoint | Body | Notes |
| --- | --- | --- |
| `GET /v1/health` | → `{status, engine, device, model_loaded, app_version, contract_version}` | Used by Settings "Test connection" and pre-flight |
| `GET /v1/capabilities` | → EngineCapabilities JSON | |
| `POST /v1/transcribe` | multipart or raw `audio/wav` (16 kHz mono PCM16) + JSON options part → TranscriptionResult JSON | Synchronous; server enforces `timeout_s`; 16 MB default body cap (~8 min audio) |
| Auth | `Authorization: Bearer <token>` on every request when token configured | |

WAV (not raw float32) on the wire keeps it curl-debuggable and content-typed. Streaming/chunked endpoints are explicitly out of scope for 0.15 (Granite isn't streaming anyway); the version field exists so they can be added later.

---

## 7. Dependency Reduction Strategy

### 7.1 Measured baseline first (Phase 0 deliverable — numbers below are estimates to be replaced)

Record in `docs/benchmarks/baseline-0.14.5.md`: `uv pip list --format json` + per-package size, `dist/speakeasy/` onedir size, installer sizes (currently 1.87 GB GPU / 202 MB CPU per README), cold/warm start time, model load time, and transcription latency on the 10/30/120 s fixture set on both CUDA and CPU.

### 7.2 Cuts that need no architecture change (ship first)

| Action | Expected saving | Risk / validation |
| --- | --- | --- |
| Replace `librosa.resample` with `soxr.resample` in `engine/audio_utils.py` (→ `core/resample.py`) | librosa + numba + llvmlite + scipy chain out of both bundles (est. 150–300 MB onedir) | Low. Add a resample-equivalence test (tolerance vs. librosa output on `assets/validation.wav`); update `test_frozen_compat.py:257` which asserts librosa in hiddenimports |
| Remove `accelerate`: load with `from_pretrained(..., torch_dtype=dtype)` + `.to(device)` instead of `device_map=` ; drop the `remove_hook_from_submodules` branch in `base.py:79` | ~50 MB + import time | Medium-low. Single-GPU/CPU only — exactly this app's shape. Validate VRAM parity on load |
| Remove `torchaudio` **iff OQ-1 confirms** the Granite `AutoProcessor` feature extractor doesn't import it (test: uninstall torchaudio in a venv, run `load()` + transcribe `validation.wav`) | ~100–300 MB (GPU build bundles its CUDA bits) | Verified empirically before merge; `test_build_naming.py:367-388` pairing asserts removed in the same PR |
| PyInstaller excludes audit: GPU spec already prunes; verify `nvidia-*` pip-side CUDA wheels aren't double-shipped alongside torch's bundled DLLs | unknown until measured | Inspect `dist/speakeasy/_internal` largest files in Phase 0 |

### 7.3 Backend benchmark matrix (Phase 5 — decide with data, not vibes)

Granite Speech 4.1 2B is a **composite** model: conformer audio encoder + projector + Granite LLM decoder driven through a chat template. That architecture is the central constraint — it is *not* a Whisper-style encoder-decoder with mature third-party runtimes.

| Backend | What to test | Expected outcome / risk |
| --- | --- | --- |
| PyTorch CUDA bf16 (baseline) | current path | Reference accuracy + speed |
| PyTorch CPU fp32 (baseline) | current path | Reference for CPU installer |
| PyTorch CPU int8 dynamic quant (`torch.ao.quantization.quantize_dynamic` on the LLM decoder) | speed/WER delta | Cheap experiment; decoder dominates latency |
| ONNX Runtime CPU / **DirectML** | export feasibility of encoder+projector+decoder, or encoder-only hybrid | **High export risk** for the chat-templated LLM decoder + cache handling; DirectML would unlock AMD/Intel GPUs — strategic if it works. Time-box the export spike |
| OpenVINO | same export via optimum-intel | Same composite-model risk; Intel-only upside |
| CTranslate2 | applicability check only | Almost certainly **N/A** — no Granite-Speech converter exists; would imply a *model* swap (e.g. faster-whisper), not a runtime swap |
| llama.cpp / GGUF | check upstream support for granite-speech multimodal | OQ-2: unknown; if supported, best path to a sub-300 MB CPU runtime |
| Remote server mode | this plan's Phase 4 | Moves the footprint problem to a box the user controls; zero accuracy risk |

**Decision rule:** a replacement backend ships only if WER on the fixture set degrades < 0.5 absolute vs. baseline AND p50 latency improves ≥ 25% (or footprint drops ≥ 40%) on target hardware. Otherwise the dependency win comes from §7.2 + the remote option, and torch stays.

**Honest framing of "replace the 1.5 GB stack":** while transformers+torch remains the only maintained Granite-Speech implementation, the GPU build has a hard floor near torch-cu128's size. The realistic levers are: (a) §7.2 trims, (b) making the **CPU build the default download** with GPU as opt-in, (c) remote mode, (d) a future torch-free UI installer once process isolation exists (UI exe ≈ PySide6 + sounddevice ≈ 150 MB, engine host downloaded separately).


---

## 8. Model Location / Remote Model Design

### 8.1 Settings schema (`config.py`)

Replace the bare `model_path: str` with a discriminated `model_source` dict serialized inside `settings.json`, plus a frozen-out legacy field for one release:

```jsonc
"model_source": {
  "type": "managed",                       // "managed" | "local_dir" | "remote"
  // local_dir (also covers external drives and UNC):
  "path": "\\\\nas01\\share\\speakeasy-models",
  // remote:
  "url": "http://10.0.0.42:8765",
  "auth_token_ref": "keyring",             // token itself stored via keyring (service "speakeasy", user "remote_asr_token") — NEVER in settings.json
  "verify_tls": true,
  "timeout_s": 10
},
"model_path": "C:\\ProgramData\\..."        // legacy mirror, written for one release for rollback
```

`ModelSource` lives in `core/model_source.py` as a frozen dataclass union with `parse(dict) -> ModelSource`, `to_dict()`, and `classify_path()` (detects UNC via `\\\\server\\share` / `Path.drive` heuristics, removable drives via `GetDriveTypeW`).

### 8.2 Per-mode behavior

| | **Managed (default)** | **Local directory** | **External / removable drive** | **UNC network share** | **Remote ASR service** |
| --- | --- | --- | --- | --- | --- |
| Meaning | `%ProgramData%\…\models`, app provisions | User-chosen folder containing `granite/` | Same, on `GetDriveTypeW == DRIVE_REMOVABLE` | `\\server\share\…` (`DRIVE_REMOTE`) | `speakeasy serve` on another machine |
| UI (Advanced → "Model Location") | Radio "Use managed location" (path shown read-only) | Radio "Custom folder" + Browse + live health badge | Same as local; non-blocking warning badge "Removable drive — model will be unavailable if disconnected" | Same as local; info badge "Network path — loads will be slower; weights are read over the network" | Radio "Remote server" + URL field + token field (password-masked, stored to keyring) + "Test connection" button |
| Validation (on Apply, async worker — never block UI thread on I/O) | none needed | `model_health()` manifest check; offer "Download here" if empty | + drive-presence check | + 5 s connect/list timeout wrapper around the manifest check; **never** auto-reset the setting on failure (replaces `config.py:147-149` behavior — see migration note) | `GET /v1/health` then `GET /v1/capabilities`; check `contract_version` |
| Error messages | — | "No Granite model found at <path>. Expected <path>\\granite\\config.json. [Download here] [Browse…]" | "Drive <X:> is not connected. Reconnect it or choose another location." | "Network path <\\\\srv\\share> is unreachable (timed out after 5 s). The saved location was kept — check VPN/network and retry." | "Could not reach <url>: <cause>." / "Server rejected the token (401)." / "Server is running contract v2; this app supports v1 — update the server." |
| Security / privacy | local-only (unchanged) | local-only | local-only; note that weights on removable media can be tampered with — health check validates manifest + JSON | SMB credentials are the OS's concern (no creds stored by app); weights traverse the LAN; loading 4–5 GB over SMB on every model load is slow — recommend "copy locally" affordance | **Audio leaves the machine.** Mandatory one-time disclosure dialog (pattern already exists: `pro_disclosure_accepted` in `config.py`) + persistent "Remote" status pill in the main window. HTTP-without-TLS allowed only for RFC1918/localhost addresses with an explicit warning; bearer token via keyring |
| Credentials | n/a | n/a | n/a | OS-level (SMB) | Bearer token, generated by `speakeasy serve --generate-token`, stored client-side in keyring |
| Health check | manifest | manifest | manifest + drive present | manifest w/ timeout | `/v1/health` on Apply, on startup, and on transcribe-failure with 3× backoff |
| Offline behavior | works (the point of the app) | works | unavailable while disconnected; status pill "Model offline", setting preserved | same | unavailable; clear status; optional "fall back to local managed model if present" checkbox (default off to keep behavior predictable) |
| Download/provision | auto (current flow) | "Download to this folder" button → provisioning | same | **disabled** by default (writing 5 GB over SMB through the elevated PS1 is fragile) — instruct user to download locally then copy | n/a (server provisions its own model) |

### 8.3 Migration from current `model_path`

In `Settings.load()` (extending the existing legacy-key block at `config.py:196-228`):

1. If `model_source` present → use it (forward path).
2. Else if `model_path == DEFAULT_MODELS_DIR` → `{type: "managed"}`.
3. Else → `{type: "local_dir", path: model_path}` — **even if the path is currently unreachable** (UNC may be offline at boot). Log, set a "needs attention" flag the UI surfaces as a badge, do not mutate.
4. Continue writing the legacy `model_path` mirror (best-effort: local path or managed default; remote sources mirror the managed default) so a downgrade to 0.14.x still boots.
5. `Settings.validate()` loses the directory-existence reset for custom paths; reachability becomes a *health state*, not a settings-validity question.

### 8.4 Server side (`speakeasy serve`)

New subcommand in `__main__.py` argparse: `speakeasy serve [--bind 127.0.0.1:8765] [--device cuda|cpu] [--model-dir PATH] [--token TOK | --generate-token] [--allow-remote]`. Refuses non-loopback bind without `--allow-remote` + a token. Reuses `InProcessEngineService`, `provisioning.ensure_model`, and the existing logging setup. Stdlib `http.server.ThreadingHTTPServer` (single inference lock — the engine is single-stream anyway) to avoid adding a web framework; revisit if streaming lands. Documented in a new `docs/REMOTE.md`.

### 8.5 Tests to add for this feature

- `tests/test_model_source.py`: parse/serialize round-trip; UNC classification (`\\\\srv\\share`, mapped drive, long-path prefix `\\\\?\\UNC\\…`); rejection of `file://` and non-http(s) URLs; token never serialized.
- `tests/test_settings_migration.py`: 0.14.5 `settings.json` fixtures → expected `model_source`; offline-UNC preservation (the regression test for C-4); legacy mirror write; downgrade-compat read.
- `tests/test_remote_client.py`: against an in-process `ThreadingHTTPServer` stub — health OK/401/timeout/refused; capabilities parse; transcribe round-trip with `FakeEngine`; contract-version mismatch; bearer header presence; TLS-verify flag plumbed.
- `tests/test_serve.py`: token enforcement; loopback-only default; `--generate-token` output; concurrent request serialization.
- `tests/test_settings_widget_model_location.py` (pytest-qt): radio switching shows/hides fields; Test-connection success/failure rendering; disclosure dialog gate before first remote Apply; removable/UNC badges.

---

## 9. UI Simplification Plan

Constraint honored throughout: **the main dictation loop (hotkey → record → transcribe → paste) is untouched in look and behavior.**

1. **Decompose `MainWindow` (2,014 LOC) without visual change.** Extract three plain-QObject controllers, leaving MainWindow as layout + signal wiring:
   - `ui/model_controller.py` — `_load_model/_on_model_loaded/_on_reload_model/_prompt_model_setup_on_start/_granite_model_ready` block (`main_window.py:880-…` and `:1646-1770`), now speaking `TranscriptionService`.
   - `ui/dictation_controller.py` — record/trim/transcribe/clipboard/professional-cleanup state machine (`:1180-1420`).
   - `ui/metrics_bridge.py` — `_on_metrics_result` + dev-panel forwarding (`:953-…`).
   The existing AST-based layout tests (`test_main_window_layout.py`, `test_integration_full_flow.py`) pin current structure; they are updated in the same PRs (see §12).
2. **Developer Panel: 7 tabs → 5.** Merge **Metrics + Logs → "Diagnostics"** (vertical splitter; both widgets already exist as `RealtimeDataWidget` / `LogsWidget` in `developer_panel.py`). Merge **AI Providers into AI Writing Profiles** as a top section — `ai_providers_widget.py` is 272 lines serving one provider choice (`openai | local_granite(future)`); a combo + key field inside the Profiles tab covers it. Resulting tabs: Settings · AI Writing Profiles · Diagnostics · History · Advanced. `Settings.dev_panel_active_tab` valid set updated with a load-time remap (`providers→pro`, `realtime/logs→diagnostics`) in the existing migration block.
3. **Advanced tab gets a "Model Location" group** (§8.2) replacing the bare `model_path` row at `settings_dialog.py:448-455`; the rest of Advanced (timeout, segmentation, diagnostics toggle) stays.
4. **Remove the `SettingsDialog` shim** (`settings_dialog.py:600+`) — it self-describes as backward-compat; grep shows no production caller. Retire `tests/test_settings_dialog.py` accordingly.
5. **Defer**: any main-window visual redesign, tray icon, onboarding. Out of scope.

## 10. Tooltip Coverage Plan

Current state: 36 `setToolTip` calls across 6 files; gaps include `history_widget.py`, `developer_panel.py` tab bar, several `pro_mode_widget.py` controls, main-window record/dev-panel buttons and status pills.

1. New `speakeasy/ui/tooltips.py`: a single `TOOLTIPS: dict[str, str]` keyed by stable IDs (`"settings.device"`, `"advanced.model_location.url"`, …) + `apply_tooltip(widget, key)` which also sets `setAccessibleDescription` for screen readers. Existing inline strings migrate into the registry (no copy changes required to start).
2. Coverage rule, enforced by test: every `QComboBox/QLineEdit/QSpinBox/QDoubleSpinBox/QCheckBox/QPushButton/ToggleSwitch` instantiated in `settings_dialog.py`, `pro_mode_widget.py`, `ai_providers_widget.py`, `history_widget.py`, and the main-window button row has a non-empty tooltip. Implementation: `tests/test_tooltips.py` instantiates each widget tree offscreen (pattern already proven in `test_settings_widget.py`) and walks `findChildren`.
3. Tab tooltips via `QTabBar.setTabToolTip` for the 5 Developer Panel tabs; status pills get plain-language tooltips ("Model: Ready — Granite loaded on GPU").
4. New Model Location controls ship with tooltips from day one (write them in the Phase 3 PR, not retrofitted).

## 11. Performance Optimization Plan

| Stage | Current cost driver | Action | Measured by |
| --- | --- | --- | --- |
| Startup | torch/transformers imported with `main_window` import (C-1) | Lazy boundary (Phase 2): UI paints first, engine imports begin on the load worker. Expect multi-second cold-start win in frozen builds | `--profile-startup` flag logging ms-to-first-paint; Phase 0 baseline vs. Phase 2 |
| Model load | 4–5 GB safetensors read; `device_map` overhead | Drop accelerate path (§7.2); document SMB-load cost in UNC mode; keep `bfloat16` on CUDA | load-time in `LoadReport`, shown in UI as today |
| Recording | already lightweight (queue + RMS gate) | no change; keep recording at device-native/16 kHz | — |
| Preprocessing | librosa resample (first call JIT-compiles numba) | soxr (§7.2) — removes first-utterance latency spike | first-vs-second utterance delta in benchmark |
| Inference | greedy decode, chunked >30 s | token budget heuristic already present (`_token_budget`); benchmark int8 CPU quant (§7.3); no algorithmic change before benchmarks | tok/s + realtime factor (already instrumented in `token_stats`) |
| Post-processing | trivial | — | — |
| Clipboard/paste | main-thread copy, worker paste — correct | no change | — |
| Metrics/logs | 5 s pynvml poll (`METRICS_POLL_MS`) | pause polling while Developer Panel hidden and model unloaded | CPU% idle sample |
| Packaging | onedir size; transformers data collection | §7.2 cuts; verify `module_collection_mode='pyz'` excludes hold after transformers upgrades | dist size in CI log |

Benchmark harness (Phase 0, kept forever): `tools/bench.py` — fixtures `tests/fixtures/audio/{10s,30s,120s}.wav` (generated/synthetic + `assets/validation.wav`), reports JSON {cold_start_ms, model_load_s, p50/p95_latency_s per fixture, rtf, peak RAM/VRAM, WER vs. committed reference transcripts}. Run on GPU and CPU profiles; results checked into `docs/benchmarks/`.


---

## 12. Test and Validation Audit

Baseline: 572 test functions, 27 files, all hardware mocked, offscreen Qt, `--timeout=120`.

### 12.1 Existing suite disposition

| Test file (fns) | Purpose | Disposition | Reason / new coverage needed | Priority |
| --- | --- | --- | --- | --- |
| `test_engine_base.py` (12) | SpeechEngine ABC contract | **Rewrite → split** | Becomes `test_contract.py` for `TranscriptionService` protocol + a parametrized conformance suite run against `InProcessEngineService(FakeEngine)` *and* `RemoteEngineClient`→stub-server. Keep ABC tests during transition | P0 |
| `test_granite_transcribe.py` (13) | Prompt building, chunking, token decode, dtype moves | **Keep, adjust imports** | Good tests of real logic; update for `TranscriptionOptions` replacing `configure_prompt_options`; must keep passing in a torch-mocked environment | P0 |
| `test_audio_utils.py` (25) | resample/chunk/stitch | **Keep + extend** | Add soxr-vs-librosa equivalence test before the swap; move resample tests to `core/resample` path | P0 |
| `test_model_presence.py` (12) | model_ready/health, startup launch paths | **Keep, extend** | Add UNC-path health-with-timeout cases; offline-source startup behavior (no destructive reset) | P0 |
| `test_model_downloader.py` (33) | download flow, progress, exit codes | **Keep** | Provisioning move is a re-export, not a rewrite; add `ensure_model` facade tests | P1 |
| `test_config.py` (27) / `test_config_persistence.py` (14) | Settings validate/save/load/migrations | **Keep + extend** | Add `model_source` migration matrix (§8.5); **rewrite** the test asserting nonexistent `model_path` resets to default — behavior intentionally changes | P0 |
| `test_frozen_compat.py` (47) | AST/spec packaging invariants | **Split + partially rewrite** | Split into `test_frozen_layout.py` (keep: stdout guards, runtime hook, Qt pruning) and `test_frozen_ml_isolation.py` (**new inverse assertions**: torch/transformers *not* imported at `speakeasy.ui`/`core` module scope; librosa assertions removed; torch/torchaudio pairing removed if OQ-1 passes) | P0 |
| `test_build_naming.py` (38) | Version consistency across pyproject/__init__/iss; torch pairing | **Keep + extend** | Add README link-version check, CHANGELOG-head check, server `contract_version`; drop torchaudio pairing per §7.2 | P1 |
| `test_main_window_layout.py` (61) / `test_integration_full_flow.py` (13) | AST pins of MainWindow structure | **Rewrite incrementally** | These will fail on every Phase 6 extraction by design; convert AST string-matching into behavior tests against the new controllers as each extraction lands; keep visual-layout pins for record row | P1 |
| `test_developer_panel_window.py` (31) / `test_developer_panel_live.py` (37) | Panel tabs, snapping, live updates | **Rewrite for 5-tab layout** | Update `_tab_key_to_index` maps, add tab-remap migration tests | P1 |
| `test_settings_widget.py` (18) | Settings tab apply/diff | **Keep** | Extend for capability-driven combos | P1 |
| `test_settings_dialog.py` (12) | Legacy modal shim | **Retire** | Shim removed (§9.4) | P2 |
| `test_professional_mode.py` (39), `test_pro_mode_widget.py` (28), `test_pro_preset.py` (24), `test_text_processor.py` (26) | AI Writing Profiles | **Keep** | Update widget tests for Providers-merge only | P1 |
| `test_audio.py` (6), `test_hotkey_registration.py` (8), `test_logging_buffer.py` (6), `test_logs_widget.py` (6), `test_metric_forwarding.py` (6), `test_realtime_widget.py` (12), `test_token_sparkline.py` (6), `test_window_icon.py` (12) | Peripheral units | **Keep** | `test_metric_forwarding`/`test_realtime_widget` adjust for `EngineStats` replacing the token tuple; logs/metrics tests adjust for Diagnostics merge | P2 |

### 12.2 New test areas (beyond §8.5)

| New tests | What they prove | Priority |
| --- | --- | --- |
| `test_fake_engine.py` | FakeEngine deterministic outputs, latency injection, failure injection — the double everything else builds on | P0 |
| `test_contract_conformance.py` | Same parametrized suite over in-process and remote implementations (load→capabilities→transcribe→stats→unload, error taxonomy mapping) | P0 |
| `test_ml_import_isolation.py` | Runs `python -c "import speakeasy.ui.main_window"` in a subprocess with a meta-path hook that **raises on `import torch/transformers/librosa/accelerate`** — the executable form of the Phase 2 guarantee | P0 |
| `test_tooltips.py` | §10 coverage rule | P1 |
| `test_ui_simplification_regressions.py` | Record button states, hotkey wiring, auto-copy/paste path survive controller extraction (pytest-qt, FakeEngine end-to-end: synthetic audio → text → mocked clipboard) | P0 |
| `test_installer_version_consistency.py` | Extends build_naming: README download URLs, RELEASE_NOTES, server contract_version all match `__version__` | P1 |
| `test_bench_smoke.py` | `tools/bench.py --smoke` runs with FakeEngine (keeps the harness from rotting) | P2 |
| Manual/CI-nightly: real-model regression | WER on fixture set vs. committed references, GPU + CPU, before/after each dependency change | P0 (gates §7 merges) |

---

## 13. Documentation Update Plan

| Doc | Changes |
| --- | --- |
| `README.md` | New "Model Location & Remote Server" section; updated architecture blurb (UI/engine/services); refreshed installer table + sizes after §7.2; dictation flow unchanged statement; link to `docs/REMOTE.md` |
| `docs/ARCHITECTURE.md` (new) | The §5 diagram, contract description, package layering rules ("`core/` and `ui/` must not import torch"), threading model, wire protocol v1 |
| `docs/REMOTE.md` (new) | `speakeasy serve` setup on a second machine, token generation, firewall/TLS guidance, privacy disclosure text |
| `SECURITY.md` | Remote-mode threat model: bearer token handling, no-plaintext-over-WAN guidance, keyring storage, what leaves the machine (audio + transcripts) in remote mode only |
| `CHANGELOG.md` | Per-phase entries under `[0.15.0]`, Keep-a-Changelog format as today |
| `CONTRIBUTING.md` | Layering rules, how to run `test_ml_import_isolation`, benchmark harness usage, FakeEngine usage for UI work |
| `RELEASE.md` / `.github/RELEASE_NOTES.md` | Add benchmark-diff and migration-test steps to the release checklist |
| Tooltip copy | Lives in code (`tooltips.py`) — reviewed as docs in the Phase 6 PR |

## 14. Versioning Plan

1. **Single source of truth:** `speakeasy/__init__.py.__version__` stays the canonical constant (frozen builds can't rely on `importlib.metadata` cleanly). `pyproject.toml` switches to hatch dynamic versioning: `dynamic = ["version"]` + `[tool.hatch.version] path = "speakeasy/__init__.py"` — removing one manual copy.
2. **Installers:** `Build-Installer.ps1` reads `__version__` and passes `/DMyAppVersion=<v>` to `iscc`, replacing the hardcoded `#define MyAppVersion "0.14.5"` in both `.iss` files (keep the `#define` as a fallback with a build-time consistency check).
3. **Wire protocol:** independent integer `CONTRACT_VERSION = 1` in `core/contract.py`, reported by `/v1/health`.
4. **Bump:** `0.15.0` at Phase 9; `0.15.0rc1..n` tags per completed phase for installer test builds. `test_build_naming.py` + new `test_installer_version_consistency.py` enforce all of the above.


---

## 15. Multi-Phase Implementation Roadmap

Sequencing note vs. the suggested order: Phase 7's *smallest practical packaging win* (librosa→soxr, accelerate removal) is pulled **forward into Phase 2.5** because it is independent of the engine rewrite and de-risks everything after it; the broader packaging cleanup remains Phase 7.

### Phase 0 — Inventory, baseline, measurement (no behavior change)
- **Objective:** lock in the numbers every later phase is judged against.
- **Files:** new `tools/bench.py`, `tools/measure_dist.py`, `tests/fixtures/audio/*`, `docs/benchmarks/baseline-0.14.5.md`; `tests/test_bench_smoke.py`.
- **Changes:** benchmark harness (§11); dist-size breakdown of `dist/speakeasy/_internal` top-50 files; dependency size table; resolve **OQ-1** (torchaudio) and **OQ-2** (GGUF) as written findings.
- **Validation:** `uv run pytest -q` (all 572 green, unchanged); `uv run python tools/bench.py --device cpu --smoke`; full bench on a GPU machine, results committed.
- **Risks:** none to product. **Rollback:** delete tools. 
- **Done when:** baseline doc merged with real GPU+CPU numbers and both open questions answered with evidence.

### Phase 1 — Formal contract + test doubles
- **Objective:** `TranscriptionService`, dataclasses, errors, FakeEngine — nothing wired into the UI yet.
- **Files:** new `speakeasy/core/{contract,errors,model_source,resample}.py`, `speakeasy/engines/fake.py`, `speakeasy/services/inprocess.py`; tests `test_contract.py`, `test_fake_engine.py`, `test_contract_conformance.py`, `test_model_source.py`.
- **Changes:** `InProcessEngineService` wraps the existing `SpeechEngine` unchanged (adapter); `TranscriptionOptions/Result/Capabilities` defined; `granite_transcribe` untouched.
- **Validation:** new tests + full suite green; `python -c "import speakeasy.core.contract"` in a venv **without torch** succeeds.
- **Risks:** contract misses a capability (mitigate: derive fields from current duck-typed surface — `configure_prompt_options`, `actual_device`, `token_stats`). **Rollback:** new modules unused; revert PR.
- **Done when:** conformance suite passes against `InProcessEngineService(FakeEngine)`.

### Phase 2 — Isolate heavy ML imports behind the boundary
- **Objective:** UI process imports no torch/transformers/librosa at module scope; MainWindow speaks only `TranscriptionService`.
- **Files:** `main_window.py` (`:61`, `:275`, `:880-940`, `:1196-1212`, `:1969`), `engine/__init__.py` → `engines/registry.py`, `engine/granite_transcribe.py` (move imports into `load()`/method bodies), `engine/base.py` (drop accelerate hook), `tests/test_ml_import_isolation.py`, splits of `test_frozen_compat.py`.
- **Changes:** registry factories (§6.2); CUDA-resume probe (`:1969`) becomes `service.health()`/device probe behind the boundary; `DedicatedWorkerPool.warmup()` ordering preserved (torch now imports on the engine thread itself — verify the DllMain invariant still holds, it should improve).
- **Tests:** import-isolation subprocess test (P0); granite tests run with torch mocked at function scope; frozen-compat rewrites.
- **Validation:** `uv run pytest`; manual smoke on GPU machine: cold start, load, dictate, sleep/resume probe; `python -X importtime -m speakeasy --version` shows no torch frames.
- **Risks:** PyInstaller misses now-dynamic imports → keep explicit hiddenimports (specs unchanged this phase); CUDA DllMain regression → explicit manual test of record-after-load on Windows. **Rollback:** revert; contract adapter keeps both shapes working mid-migration.
- **Done when:** isolation test green; frozen GPU build dictates end-to-end.

### Phase 2.5 — Early dependency cuts (the "smallest practical packaging improvement")
- **Objective:** librosa→soxr; remove accelerate; remove torchaudio iff OQ-1 cleared.
- **Files:** `core/resample.py`, `engine/audio_utils.py`, `engine/base.py`, `granite_transcribe.py` (`from_pretrained` device handling), `pyproject.toml`, both specs, `hooks/`, `test_audio_utils.py`, `test_build_naming.py:367-388`, `test_frozen_compat` splits.
- **Validation:** resample-equivalence test; real-model WER regression run (must be bit-identical transcripts on fixtures — resampling differences make this *near*-identical; gate on WER delta < 0.1); rebuild both installers, record size deltas vs. Phase 0.
- **Risks:** Granite processor secretly needs torchaudio (OQ-1 protects); soxr numerical drift (equivalence test). **Rollback:** single-PR revert; deps restored from uv.lock history.
- **Done when:** both installers rebuilt, dictation verified, size reduction documented.

### Phase 3 — Model location schema + Advanced UI redesign
- **Objective:** `model_source` (§8.1–8.3) with managed/local/UNC modes live; remote mode UI present but disabled behind a "Remote server (requires SpeakEasy Server)" placeholder until Phase 4.
- **Files:** `config.py`, `core/model_source.py`, `settings_dialog.py` (`AdvancedSettingsWidget` model section `:441-470`, `:567-592`), `main_window.py` model controller paths, `services/provisioning.py` (absorb download trigger from `granite_transcribe.load()` — closes C-2), tests per §8.5 (migration, widget) + `test_config` updates.
- **Validation:** migration fixture matrix; manual: set UNC path with share offline → restart → setting preserved + badge; download-to-custom-folder flow.
- **Risks:** silent-reset behavior change surprises a user whose path was *legitimately* dead (mitigate: needs-attention badge + log line). **Rollback:** legacy `model_path` mirror means reverting the code reverts the behavior; settings stay readable both directions for one release.
- **Done when:** all modes except remote work end-to-end on a frozen build.

### Phase 4 — Remote ASR service (server + client)
- **Objective:** `speakeasy serve` + `RemoteEngineClient`; remote radio enabled with disclosure dialog.
- **Files:** `services/{server,remote_client}.py`, `__main__.py` (subcommand), `core/contract.py` (CONTRACT_VERSION), `settings_dialog.py` (enable remote fields, Test connection), keyring integration mirroring `text_processor.py`'s pattern, `docs/REMOTE.md`, `SECURITY.md`; tests `test_remote_client.py`, `test_serve.py`, remote leg of conformance suite.
- **Validation:** two-machine LAN test (GPU desktop serving, laptop client): health, capabilities, 10/30/120 s dictation, token rejection, server-down mid-session UX; loopback self-serve test on one machine.
- **Risks:** privacy posture dilution (mitigate: disclosure + pill + docs); auth misuse on WAN (mitigate: loopback default, `--allow-remote` + token required, no UPnP, docs say "LAN/VPN only"). **Rollback:** feature-flag the radio (`remote_enabled` constant); server subcommand is additive.
- **Done when:** conformance suite green over real HTTP; two-machine demo recorded in docs.

### Phase 5 — Backend experiments + benchmark matrix
- **Objective:** execute §7.3 with the Phase 0 harness; produce a written go/no-go per backend.
- **Files:** `docs/benchmarks/backends-0.15.md`; experimental branches only — nothing merges to main except the report and (if a backend passes the §7.3 decision rule) a new `engines/<backend>/` behind the registry.
- **Validation:** WER + latency tables per backend per device; decision-rule applied.
- **Risks:** time sink on ONNX export of the composite model — **time-box each export spike to 3 days**; failure is an acceptable, documented outcome. **Rollback:** experiments live on branches.
- **Done when:** report merged with explicit ship/park decision per backend.

### Phase 6 — UI simplification + tooltips
- **Objective:** §9 controller extraction, 5-tab panel, shim removal; §10 tooltip registry + coverage test.
- **Files:** `main_window.py` → `ui/{model_controller,dictation_controller,metrics_bridge}.py`, `developer_panel.py`, `ai_providers_widget.py` (folded), `settings_dialog.py`, new `ui/tooltips.py`; rewrites of `test_main_window_layout.py`, `test_integration_full_flow.py`, panel tests; new `test_tooltips.py`, `test_ui_simplification_regressions.py`.
- **Validation:** pytest-qt regression suite with FakeEngine; manual dictation smoke; tab-state migration check.
- **Risks:** the 61-test AST layout suite churns — rewrite tests in the same commits as extractions, never after. **Rollback:** extractions are mechanical moves; per-extraction commits revert cleanly.
- **Done when:** MainWindow < ~900 LOC, tooltip test green, dictation behavior pixel/behavior-identical.

### Phase 7 — Packaging/build workflow cleanup
- **Objective:** consolidate specs (shared `spec_common.py`, variant via `--` argument instead of live-patching `_build_variant.py`); version injection into `.iss` (§14.2); prune audit informed by Phase 2/2.5 (hiddenimports list shrinks); optional: evaluate UI-only installer feasibility report (depends on Phase 4 local self-serve).
- **Files:** both `.spec` files, `installer/Build-Installer.ps1`, both `.iss`, `hooks/hook-transformers.py`, `test_frozen_layout.py`, `test_installer_version_consistency.py`.
- **Validation:** build GPU+CPU+source modes via `Build-Installer.ps1`; install/uninstall/upgrade-keeping-models cycle; size vs. baseline.
- **Risks:** Inno upgrade-path regressions (the `.iss` has permission-repair logic for older installs — preserve verbatim). **Rollback:** specs/iss are leaf files; revert freely.
- **Done when:** one-command `-Variant Both` build passes the install/upgrade matrix.

### Phase 8 — Test suite audit execution
- **Objective:** execute the §12.1 table in full: splits, rewrites, retirements; conformance suite as the spine; nightly real-model job documented.
- **Files:** `tests/` per table; `CONTRIBUTING.md`.
- **Validation:** `uv run pytest -n auto` wall-time ≤ baseline +20%; coverage on `core/` + `services/` ≥ 90%.
- **Risks:** deleting tests that silently guarded behavior — every retirement PR states what now covers it. **Rollback:** git.
- **Done when:** zero references to retired APIs (`SettingsDialog`, `configure_prompt_options`, bare `model_path` semantics) anywhere in tests.

### Phase 9 — Docs, version, release
- **Objective:** §13 docs, §14 versioning, `0.15.0` release.
- **Files:** all docs, `pyproject.toml` (dynamic version), `__init__.py`, both `.iss` fallbacks, README installer table with new measured sizes.
- **Validation:** `test_build_naming` + `test_installer_version_consistency`; full release cycle via `Build-Installer.ps1 -Mode Release`; fresh-install + upgrade-from-0.14.5 (settings migration verified on a real old `settings.json`).
- **Rollback:** standard release rollback — keep 0.14.5 installers linked.
- **Done when:** tagged `v0.15.0`, checksums published, CHANGELOG complete.

---

## 16. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| R-1 | CUDA DllMain/thread hazard resurfaces when import timing changes (Phase 2) | Med | High (hangs/AVs on user machines) | Keep `DedicatedWorkerPool.warmup()`; import torch *on* the engine thread; explicit Windows manual test in Phase 2 DoD; CPU build unaffected |
| R-2 | PyInstaller drops now-lazy imports | Med | High (frozen build broken) | hiddenimports unchanged until Phase 7; frozen smoke test in every phase's DoD |
| R-3 | torchaudio actually required by Granite processor | Med | Low (keep it) | OQ-1 empirical test in Phase 0 gates §7.2 |
| R-4 | ONNX/OpenVINO export of composite Granite model infeasible | High | Low (status quo persists) | Time-boxed spikes; remote mode is the fallback footprint answer |
| R-5 | Replacing Granite runtime stack breaks accuracy subtly (quantization, resampler drift) | Med | High (product's WER claim) | WER gate (<0.5 abs) on committed fixtures for every inference-path change; soxr equivalence test |
| R-6 | Remote mode erodes "nothing leaves your computer" brand promise | Med | Med | Off by default; disclosure dialog; persistent pill; README/SECURITY language reviewed; loopback-only server default |
| R-7 | UNC model loads are painfully slow (4–5 GB over SMB per load) | High | Med (user disappointment) | UI warning badge + "copy locally" guidance; documented expectation |
| R-8 | Settings migration corrupts configs in the wild | Low | High | Fixture matrix incl. malformed JSON; legacy mirror enables downgrade; migration only adds keys |
| R-9 | AST-pinned test suites (layout/frozen/integration) create rewrite churn and mask regressions during Phase 6 | High | Med | Rewrite tests in the same commit as each extraction; behavior tests with FakeEngine replace string pins |
| R-10 | `speakeasy serve` exposed to hostile networks | Low | High | Loopback default, mandatory token for non-loopback, no TLS termination claim (recommend VPN/stunnel in docs), body-size caps, single-worker lock |
| R-11 | transformers major-version churn breaks Granite loading (spec already works around ≥5.5 disk-scanning) | Med | Med | Pin transformers minor in uv.lock; frozen import test; hook-transformers maintained |

## 17. Acceptance Criteria (for the whole program)

1. `python -c "import speakeasy.ui.main_window, speakeasy.core.contract, speakeasy.services.remote_client"` succeeds in a venv with **no torch/transformers/librosa/accelerate installed** (enforced by `test_ml_import_isolation.py`).
2. Dictation flow (hotkey → record → transcribe → auto-copy/paste) is behaviorally identical to 0.14.5 on both GPU and CPU frozen builds; WER on the fixture set within 0.5 abs of the Phase 0 baseline.
3. All four model-location modes work as specified in §8.2, including: offline-UNC setting preserved across restarts; remote mode requires disclosure acceptance + shows a persistent indicator; tokens stored only in keyring.
4. A `settings.json` written by 0.14.5 loads cleanly into 0.15.0 (and a 0.15.0 file with the legacy mirror boots 0.14.5).
5. Installer sizes reduced vs. the Phase 0 baseline by the §7.2 cuts (target: ≥150 MB off GPU onedir; CPU at or below current 202 MB) — actual numbers recorded, not promised.
6. `speakeasy serve` on machine A + remote client on machine B passes the conformance suite and a manual two-machine dictation session.
7. Tooltip coverage test green; Developer Panel has 5 tabs with state migration; `MainWindow` reduced below ~900 LOC with the regression suite green.
8. Version `0.15.0` consistent across `__init__.py` (source of truth), generated pyproject metadata, both installers, README links, CHANGELOG — enforced by tests.
9. Test suite: conformance suite runs against both service implementations; retired tests documented; wall time ≤ baseline +20%.
10. Docs: ARCHITECTURE.md, REMOTE.md, updated SECURITY/README/CONTRIBUTING merged.

## 18. Open Questions

| ID | Question | Owner phase | How it resolves |
| --- | --- | --- | --- |
| OQ-1 | Does the Granite `AutoProcessor`/feature extractor import torchaudio at load or inference time? (Zero direct app references found; pyproject + hiddenimports + version-pairing tests treat it as required.) | Phase 0 | Venv without torchaudio: `load()` + transcribe `assets/validation.wav` |
| OQ-2 | Does llama.cpp/GGUF (or any sub-torch runtime) support granite-speech-4.1's audio encoder + projector? | Phase 0 (research) / Phase 5 (spike) | Upstream issue/PR search + conversion attempt |
| OQ-3 | Is `dist/speakeasy/_internal` double-shipping CUDA DLLs (torch-bundled + pip `nvidia-*` wheels)? | Phase 0 | Dist file-size audit |
| OQ-4 | Should the CPU installer become the default README recommendation post-§7.2 (smaller funnel, GPU as power-user path)? | Phase 9 | Product call, informed by benchmark CPU latency |
| OQ-5 | Auto-fallback from unreachable remote source to local managed model: default on or off? (Plan says off for predictability.) | Phase 4 | User feedback on rc builds |
| OQ-6 | Local out-of-process engine host (UI-only installer): pursue in 0.16? Depends on Phase 4 client stability + R-1 evidence. | Post-0.15 | Feasibility report in Phase 7 |
| OQ-7 | Is `Settings.sample_rate` user-exposure still warranted once resampling is client-side and soxr-based, or should it become fixed-16 kHz with a hidden override? | Phase 6 | Advanced-tab review |
| OQ-8 | `provider: local_granite (future)` in AI Providers — is local LLM cleanup still on the roadmap (affects how aggressively the Providers tab is folded)? | Phase 6 | Maintainer decision |

---

*End of plan. All file paths, line numbers, counts, and behaviors cited were verified against commit `2a357a5`; items not verifiable from the repository are labeled as assumptions or open questions (OQ-1…OQ-8).*
