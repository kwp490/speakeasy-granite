# SpeakEasy AI — Baseline Measurements (0.14.5)

Phase 0 deliverable of the re-architecture plan. This document locks in the
numbers and findings every later phase is judged against. It is generated with
the committed harness, not by hand:

```powershell
# Dependency + frozen-onedir sizes
.\.venv\Scripts\python.exe tools/measure_dist.py --deps --top 50
.\.venv\Scripts\python.exe tools/measure_dist.py --dist dist/speakeasy/_internal --top 50

# Runtime benchmark (per device)
.\.venv\Scripts\python.exe tools/bench.py --device cuda --output docs/benchmarks/run-gpu.json
.\.venv\Scripts\python.exe tools/bench.py --device cpu  --output docs/benchmarks/run-cpu.json
```

- **Commit baseline:** `2a357a5` (tag `v0.14.5`)
- **Measurement date:** 2026-06-15
- **Fixtures:** `tests/fixtures/audio/{10s,30s,120s}.wav` (synthetic, seeded) plus
  `speakeasy/assets/validation.wav` (real speech, reference =
  "testing one two three"). References in
  `tests/fixtures/audio/references.json`.

> Status legend: ✅ measured here · ⏳ PENDING — requires benchmark hardware
> (GPU + CPU) with the Granite model downloaded, and a frozen onedir build.

---

## 1. Dependency size table ✅

Measured in the project virtual environment
(`.venv`, CPython 3.11, Windows AMD64 / `pytorch-cu128`). Total installed
`site-packages`: **≈ 5,349 MB**.

| Package | Size | Notes |
| --- | --- | --- |
| torch | 4,189.8 MB | Dominant cost; cu128 build with bundled CUDA DLLs. Hard floor for the GPU bundle. |
| PySide6 | 627.7 MB | UI toolkit; trimmed at freeze time by the spec excludes. |
| llvmlite | 102.7 MB | **librosa chain** (via numba). |
| scipy | 98.0 MB | **librosa chain.** |
| sympy | 40.9 MB | torch dep. |
| transformers | 46.1 MB | Required (only maintained Granite-Speech impl). |
| sklearn | 27.1 MB | pulled in transitively. |
| numpy | 23.5 MB + 20.0 MB (`numpy.libs`) | core. |
| scipy.libs | 19.3 MB | **librosa chain.** |
| numba | 18.2 MB | **librosa chain.** |
| networkx | 11.2 MB | torch dep. |
| torchaudio | 9.9 MB (site-packages) | **Required — see OQ-1.** GPU bundle additionally ships CUDA bits. |
| hf_xet | 7.9 MB | download transport. |
| tokenizers | 7.3 MB | transformers dep. |
| openai | 7.2 MB | AI Writing Profiles. |
| accelerate | 2.7 MB | small on disk; targeted in §7.2 mainly for import-time / `device_map` simplification. |
| librosa | 3.4 MB | **librosa chain** (the import that drags in numba/llvmlite/scipy). |
| sentencepiece | 2.5 MB | tokenizer. |

**librosa removal envelope (§7.2 target):** librosa (3.4) + numba (18.2) +
llvmlite (102.7) + scipy (98.0) + scipy.libs (19.3) ≈ **241.6 MB** of
`site-packages` that the `soxr` swap can shed, *iff* nothing else pulls scipy
back in. (sklearn also imports scipy; verify the onedir actually drops it after
the swap — see §3.)

Full machine-readable table: run `tools/measure_dist.py --deps --output
docs/benchmarks/deps-0.14.5.json`.

---

## 2. Runtime benchmark ⏳

To be filled by running `tools/bench.py` on benchmark hardware with the Granite
model present. The harness emits this exact schema (see `tools/bench.py`):

| Fixture | Duration | p50 latency | p95 latency | RTF | WER |
| --- | --- | --- | --- | --- | --- |
| validation.wav | ~4 s | ⏳ | ⏳ | ⏳ | ⏳ (ref committed) |
| 10s.wav | 10 s | ⏳ | ⏳ | ⏳ | n/a (synthetic) |
| 30s.wav | 30 s | ⏳ | ⏳ | ⏳ | n/a (synthetic) |
| 120s.wav | 120 s | ⏳ | ⏳ | ⏳ | n/a (synthetic) |

| Metric | CUDA bf16 | CPU fp32 |
| --- | --- | --- |
| cold_start_ms | ⏳ | ⏳ |
| model_load_s | ⏳ | ⏳ |
| peak_ram_mb | ⏳ | ⏳ |
| peak_vram_mb | ⏳ | n/a |

WER is computed only where a committed reference exists; the synthetic
fixtures carry `null` references and exist solely to time the
record → resample → chunk → inference path at known durations.

Smoke validation (no torch / no model, CI) ✅:

```
.\.venv\Scripts\python.exe tools/bench.py --smoke --device cpu
```

emits a schema-valid report (engine `smoke`) and is guarded by
`tests/test_bench_smoke.py`.

---

## 3. Frozen onedir breakdown ⏳

Requires a build (`dist/speakeasy/_internal` does not exist in a clean
checkout). After `Build-Installer.ps1` produces the onedir:

```
.\.venv\Scripts\python.exe tools/measure_dist.py --dist dist/speakeasy/_internal --top 50 --output docs/benchmarks/dist-0.14.5.json
```

Inspect the top-50 for the §7.2 PyInstaller audit item: confirm whether
`nvidia-*` pip-side CUDA wheels are double-shipped alongside torch's bundled
CUDA DLLs in the GPU build.

Reference installer sizes (per README, 0.14.5): **1.87 GB** GPU / **202 MB**
CPU.

---

## 4. Open questions resolved

### OQ-1 — Does the Granite processor require torchaudio? ✅ **YES — keep it.**

**Finding: torchaudio is a hard requirement of the Granite feature
extractor.** Static + runtime inspection of the installed
`transformers/models/granite_speech/feature_extraction_granite_speech.py`:

- Imports guarded as `if is_torchaudio_available(): import torchaudio`.
- The feature extractor calls `requires_backends(self, ["torchaudio"])` and
  builds its mel front-end with
  `self.mel_filters = torchaudio.transforms.MelSpectrogram(**self.melspec_kwargs)`.
- Source comment: *"currently we have a dependency on torch/torchaudio
  anyway."*

The module *imports* without torchaudio (lazy guard), but **constructing** the
processor — which `GraniteTranscribeEngine.load()` does via
`AutoProcessor.from_pretrained(...)` — needs `torchaudio.transforms`.

**Consequence:** §7.2's "remove torchaudio" line item is **rejected**; risk
**R-3 resolves to "keep it."** Do not drop the `torch`/`torchaudio` version
pairing in `test_build_naming.py`. Confirmation command (returns the
`requires_backends`/`MelSpectrogram` evidence):

```powershell
$tf = .\.venv\Scripts\python.exe -c "import transformers,os;print(os.path.dirname(transformers.__file__))"
Select-String -Path "$tf\models\granite_speech\*.py" -Pattern "torchaudio|requires_backends|MelSpectrogram"
```

### OQ-2 — Does llama.cpp / GGUF support granite-speech? ✅ **YES — native support exists.**

**Finding (upgraded from "unknown"): llama.cpp has first-class
`granite_speech` audio support in its multimodal (`mtmd`) stack** as of current
`main` (`ggml-org/llama.cpp`). Evidence (code search):

- `tools/mtmd/clip-impl.h`: `PROJECTOR_TYPE_GRANITE_SPEECH` enum + name
  `"granite_speech"`.
- `tools/mtmd/models/granite-speech.cpp` / `models.h`:
  `clip_graph_granite_speech::build()` implements the conformer encoder +
  q-former projector graph (CTC mid-layer, conv kernel, chunked attention).
- `tools/mtmd/mtmd-audio.{h,cpp}`:
  `mtmd_audio_preprocessor_granite_speech` performs the mel preprocessing
  (replacing the torchaudio mel front-end).
- `conversion/granite.py` + `gguf-py/gguf/constants.py`
  (`GRANITE_SPEECH = "granite_speech"`): GGUF conversion writes the
  `GRANITE_SPEECH` audio projector, mel-bin count, chunk size, etc.
- `gguf-py/gguf/tensor_mapping.py`: encoder/q-former tensor name mappings for
  `granite_speech`.

The HF model card (`ibm-granite/granite-speech-*`) still lists only
`transformers` (requiring `torchaudio peft soundfile`) and `vLLM` as the
"official" runtimes — both torch-based — but llama.cpp's mtmd path is a real,
merged third option.

**Consequence:** the §7.3 / Phase 5 row for llama.cpp/GGUF moves from
"unknown" to **"feasible — run the spike."** This is the most promising path to
a sub-300 MB CPU runtime. Phase 0 only confirms *support exists*; the Phase 5
go/no-go still requires converting `granite-speech-4.1-2b` to GGUF and
measuring WER (< 0.5 abs vs. this baseline) and p50 latency on target CPU
hardware before it can replace the torch CPU path.

> **Phase 5 update:** the per-backend go/no-go report is now in
> [backends-0.15.md](backends-0.15.md). llama.cpp granite-speech support is
> confirmed in code but is **not** in llama.cpp's documented pre-quantized
> audio-model list and audio is flagged "highly experimental" — so the GGUF row is
> decided **PARK — run the 3-day spike**, with the WER gate as the live risk.

---

## 5. What still blocks "done"

Phase 0 is complete on tooling, fixtures, the dependency table, and both open
questions. The remaining ⏳ items (runtime numbers on GPU + CPU, frozen-onedir
top-50) require running the committed harness on benchmark hardware with the
Granite model downloaded and a release build produced; fill them in here and
commit the JSON sidecars under `docs/benchmarks/`.
