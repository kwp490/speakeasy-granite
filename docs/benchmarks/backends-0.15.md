# SpeakEasy AI — Backend Experiments & Go/No-Go (0.15)

Phase 5 deliverable of the re-architecture plan
([REARCHITECTURE-PLAN.md §7.3 / §15](../REARCHITECTURE-PLAN.md)). This document
executes the backend matrix with the Phase 0 harness and records an **explicit
ship/park decision per backend**, applying the §7.3 decision rule.

- **Commit context:** Phase 4 complete (`speakeasy serve` + `RemoteEngineClient`
  live; conformance suite green over real HTTP). Version `0.15.0`.
- **Baseline reference:** [baseline-0.14.5.md](baseline-0.14.5.md).
- **Harness:** `tools/bench.py` (WER + p50/p95 latency + RTF schema, `--smoke` in CI).
- **Fixtures:** `tests/fixtures/audio/{10s,30s,120s}.wav` (synthetic, timing only)
  + `speakeasy/assets/validation.wav` (real speech, ref "testing one two three").

> Status legend: ✅ decided from architecture/feasibility evidence (no hardware
> needed) · ⏳ PENDING — requires benchmark hardware (GPU + CPU) with the Granite
> model present, plus an experiment branch build. Hardware-dependent measurement
> cells follow the same `⏳` convention as the baseline doc — a worker on
> benchmark hardware fills the numbers and commits the JSON sidecars.

---

## 1. Decision rule (from §7.3)

A replacement backend **ships** only if **both** hold on target hardware:

1. **WER** on the fixture set degrades **< 0.5 absolute** vs. the torch baseline, **AND**
2. **p50 latency improves ≥ 25%** *(or footprint drops ≥ 40%)*.

Otherwise the backend is **parked** (kept on an experiment branch, documented
here) and the dependency win comes from §7.2 trims + the Phase 4 remote option,
with torch remaining the default runtime.

**Time-box:** each export/conversion spike (ONNX, OpenVINO, GGUF) is capped at
**3 days**. A failed spike is an acceptable, documented outcome (risk R-4).

---

## 2. The constraint: Granite Speech is a composite model

The central fact that governs every backend decision is the model's shape.
Granite Speech 4.1 is **not** a Whisper-style encoder-decoder with mature
third-party runtimes — it is a three-stage composite driven through a chat
template. Verified from the installed `config.json`
(`dev-temp/models/granite/config.json`):

| Stage | Type | Key params |
| --- | --- | --- |
| Audio encoder | `granite_speech_encoder` (Conformer) | 16 layers, hidden 1024, mel input 160, conv kernel 15, context 200, output 348 |
| Projector | `blip_2_qformer` | 2 hidden layers, hidden 1024, 16 heads, `cross_attention_frequency=1`, `downsample_rate=5` |
| Text decoder | `GraniteForCausalLM` (`granite-4.0-1b-base`) | 40 layers, hidden 2048, 4 KV heads (GQA), vocab 100353, `audio_token_index=100352` |

Audio embeddings from the encoder→projector are spliced into the LLM token
stream at the `audio_token_index` placeholder, then the **Granite 4.0 1B**
decoder generates greedily through a chat template. The mel front-end is
`torchaudio.transforms.MelSpectrogram` (OQ-1, [baseline](baseline-0.14.5.md) §4).

**Implication for every "swap the runtime" idea:** a runtime must reimplement
*three* graphs plus the chat-templated KV-cache decode loop — not one. Generic
exporters target single architectures; the decoder is exportable in isolation,
the conformer encoder + Q-Former projector are not. This is why the matrix below
is dominated by **export-feasibility** verdicts, not latency numbers.

---

## 3. Backend matrix — verdicts

| Backend | Target | Decision | Basis |
| --- | --- | --- | --- |
| PyTorch CUDA bf16 | GPU | **SHIP (baseline / default)** | ✅ Reference accuracy + speed; only maintained runtime |
| PyTorch CPU fp32 | CPU | **SHIP (baseline / default)** | ✅ Reference for the CPU installer |
| PyTorch CPU int8 dynamic quant | CPU | **PARK — run spike for numbers** | ⏳ Cheap, low-risk; decision gated on WER+latency run |
| ONNX Runtime (CPU / DirectML) | CPU / any GPU | **PARK — export infeasible out-of-box** | ✅ `granite_speech` not in optimum exporters; composite custom export = high risk |
| OpenVINO (optimum-intel) | Intel CPU/GPU | **PARK — same composite risk, Intel-only upside** | ✅ Same export gap as ONNX; strictly narrower payoff |
| CTranslate2 | CPU/GPU | **PARK — N/A (no converter)** | ✅ No Granite-Speech converter exists; would be a model swap |
| llama.cpp / GGUF | CPU (sub-300 MB) | **PARK — promising; run the 3-day spike** | ✅ Code support exists; ⏳ not in pre-quantized list; needs conversion + WER |
| Remote server mode | user's box | **SHIPPED (Phase 4)** | ✅ Moves footprint off the client; zero accuracy risk |

---

## 4. Per-backend findings

### 4.1 PyTorch CUDA bf16 — **SHIP (baseline)**

The current default. Reference for the decision rule. No change. Fill the
baseline numbers via `tools/bench.py --device cuda` on GPU hardware.

| Fixture | p50 latency | p95 latency | RTF | WER |
| --- | --- | --- | --- | --- |
| validation.wav (~4 s) | ⏳ | ⏳ | ⏳ | ⏳ (ref committed) |
| 10s.wav | ⏳ | ⏳ | ⏳ | n/a |
| 30s.wav | ⏳ | ⏳ | ⏳ | n/a |
| 120s.wav | ⏳ | ⏳ | ⏳ | n/a |

### 4.2 PyTorch CPU fp32 — **SHIP (baseline)**

Reference for the CPU installer. The footprint here (≈202 MB CPU installer, per
README) is what the §7.3 alternatives must beat by ≥40% to justify the risk.
Fill via `tools/bench.py --device cpu`.

### 4.3 PyTorch CPU int8 dynamic quant — **PARK (run spike for numbers)**

**What:** `torch.ao.quantization.quantize_dynamic` over the **LLM decoder's
`nn.Linear` layers** (the decode loop dominates latency at 40 layers). The
encoder/projector are run once per utterance; the decoder runs per generated
token, so int8 there is where the latency lever is.

**Feasibility:** ✅ low-risk — no export, no graph surgery, pure runtime. It is a
*speed/footprint* experiment, **not** a footprint-floor change: torch + the
safetensors weights still ship, so this does **not** get under the §7.2 floor.
The win, if any, is CPU p50 latency.

**Risk:** dynamic int8 on a GQA Granite decoder may degrade WER and/or fail to
beat fp32 on modern AVX-512/VNNI CPUs where fp32 GEMM is already fast. Granite's
attention/embedding multipliers (`attention_multiplier`, `embedding_multiplier`,
`logits_scaling`) make it more quantization-sensitive than a vanilla Llama.

**Decision:** **PARK pending the spike run** — it cannot ship without the
WER+latency numbers below, and it does not change the dependency footprint, so it
is not a release-blocker. Recommended as the *first* spike (cheapest).

Experiment recipe (runs on the engine; experiment branch only):

```python
# experiment branch: engines/granite_int8/engine.py (do NOT merge to main)
import torch
from torch.ao.quantization import quantize_dynamic
# after AutoModelForSpeechSeq2Seq.from_pretrained(..., torch_dtype=torch.float32):
model.language_model = quantize_dynamic(
    model.language_model, {torch.nn.Linear}, dtype=torch.qint8
)
```

| Metric (CPU) | fp32 baseline | int8 dynamic | Δ |
| --- | --- | --- | --- |
| validation.wav WER | ⏳ | ⏳ | must be < 0.5 abs |
| p50 latency (30s) | ⏳ | ⏳ | must improve ≥ 25% |
| peak_ram_mb | ⏳ | ⏳ | — |

### 4.4 ONNX Runtime (CPU / DirectML) — **PARK (export infeasible out-of-box)**

**Feasibility evidence (current):** the 🤗 Optimum ONNX exporter supports
**`Granite`** (the text LLM) but has **no `granite_speech` / `GraniteSpeechFor
ConditionalGeneration`** entry in its supported-architectures list
(verified against the optimum-onnx exporter overview). Likewise the conformer
`granite_speech_encoder` and the `blip_2_qformer` projector are not covered.

**Consequence:** an ONNX path requires **hand-authoring** the export of (a) the
conformer encoder, (b) the Q-Former projector, and (c) the chat-templated Granite
decoder with KV-cache — three separate exports plus a custom audio-token splice
and a generate loop reimplemented on ORT. The decoder export is plausible (Granite
is supported); the encoder + projector + cache plumbing is the **high-risk**
portion (R-4). DirectML is the strategically interesting target (AMD/Intel GPU
unlock), so if any export effort is funded it should target the DirectML EP — but
only after a time-boxed encoder-export feasibility probe.

**Decision:** **PARK.** Time-box a 3-day encoder-only export probe; do not attempt
the full composite for 0.15. If the encoder probe succeeds and someone wants
DirectML, revisit in a later cycle. Remote mode (Phase 4) is the footprint answer
in the meantime.

### 4.5 OpenVINO (optimum-intel) — **PARK (same risk, narrower upside)**

Same export pathway and the same `granite_speech` gap as §4.4, routed through
optimum-intel instead of optimum-onnx. The upside is **Intel-only** (CPU/iGPU/NPU)
— strictly narrower than DirectML's any-GPU reach for the same composite-export
cost. **Decision: PARK**; dominated by the ONNX/DirectML option for equal effort.

### 4.6 CTranslate2 — **PARK (N/A — no converter)**

CTranslate2's converters target a fixed model set (Whisper, Wav2Vec2, Transformer
NMT, a handful of decoder LLMs) — **there is no Granite-Speech converter**.
Adopting CT2 would mean **replacing the model** (e.g. faster-whisper), not
swapping the runtime — which fails the WER gate's premise (it is no longer
Granite) and is out of scope for a runtime experiment. **Decision: PARK (N/A).**

### 4.7 llama.cpp / GGUF — **PARK (promising; run the 3-day spike)**

This is the **most promising** path to a sub-300 MB CPU runtime and the resolution
of **OQ-2**. The picture is genuinely mixed and must be stated honestly:

**Supports it (code):** llama.cpp's multimodal (`mtmd`) stack contains first-class
granite-speech machinery — `PROJECTOR_TYPE_GRANITE_SPEECH`,
`tools/mtmd/models/granite-speech.cpp` (`clip_graph_granite_speech::build()`:
conformer encoder + Q-Former projector, CTC mid-layer, chunked attention),
`mtmd_audio_preprocessor_granite_speech` (mel front-end replacing torchaudio), and
`conversion/granite.py` + GGUF constants/tensor-mappings for the `GRANITE_SPEECH`
projector ([baseline](baseline-0.14.5.md) §4, OQ-2).

**Caveats (current, this phase):**
- granite-speech is **not** in llama.cpp's documented *pre-quantized / supported*
  audio-model list (`docs/multimodal.md` lists Ultravox, Qwen2-Audio, SeaLLM-Audio,
  Voxtral, Qwen3-ASR, Qwen2.5/Qwen3-Omni — **not** granite-speech). Support exists
  in code but is not advertised as a blessed, regression-tested path → higher spike
  risk than a listed model.
- llama.cpp itself flags audio input as **"highly experimental and may have reduced
  quality."** That directly threatens the WER gate.
- Our model is granite-speech **4.1** (Granite 4.0 1B decoder); confirm the
  conversion script handles this exact revision and its `chat_template.jinja`.

**The spike (do this on an experiment branch, ≤3 days):**

```bash
# 1. Convert HF → GGUF (text + audio projector mmproj)
python convert_hf_to_gguf.py dev-temp/models/granite --outfile granite-speech.gguf
python tools/mtmd/legacy-models/granite_speech_convert_encoder.py ...  # or conversion/granite.py path
# 2. Quantize the decoder (Q4_K_M / Q5_K_M / Q8_0 sweep)
llama-quantize granite-speech.gguf granite-speech-Q5_K_M.gguf Q5_K_M
# 3. Transcribe the fixture set via llama-mtmd-cli, score WER with tools/bench.py's _wer
llama-mtmd-cli -m granite-speech-Q5_K_M.gguf --mmproj mmproj-granite-speech.gguf \
  --audio speakeasy/assets/validation.wav -p "<chat-template transcribe prompt>"
```

| Metric (CPU) | torch fp32 | GGUF Q5_K_M | gate |
| --- | --- | --- | --- |
| validation.wav WER | ⏳ | ⏳ | < 0.5 abs vs. baseline |
| p50 latency (30s) | ⏳ | ⏳ | ≥ 25% faster *or* |
| runtime footprint | ~torch floor | ⏳ (target < 300 MB) | ≥ 40% smaller |

**Decision: PARK — run the spike.** If the GGUF spike clears the WER gate **and**
the footprint gate, it becomes the first real candidate to ship as
`engines/granite_gguf/` behind the registry (the registry already supports
deps-gated, lazy backends — [Phase 2](../REARCHITECTURE-PROGRESS.md)). If WER fails
(likely, given the "experimental/reduced quality" warning), it is parked with this
report as the record. **This is the recommended highest-value spike of Phase 5.**

### 4.8 Remote server mode — **SHIPPED (Phase 4)**

Already delivered: `speakeasy serve` + `RemoteEngineClient` move the entire
footprint problem onto a box the user controls, at zero accuracy risk (the server
runs the identical torch path). This is the **production answer** to "I don't want
1.5 GB on this machine" today — and the architectural payoff carries into the
optional Phase 5+ local out-of-process host (`speakeasy serve --bind 127.0.0.1:0`
auto-spawned by the UI), which reuses the *identical* remote client and would
retire the C-6 CUDA-DllMain warmup hazard (R-1). Keep that optional and
benchmark-gated; in-process stays the default.

---

## 5. Overall Phase 5 conclusion

**No backend swap merges to main in 0.15.** The honest framing from §7.3 holds:
while transformers+torch is the only maintained Granite-Speech implementation, the
GPU build has a hard floor near torch-cu128's size, and the composite-model shape
makes every generic exporter (ONNX/OpenVINO/CT2) infeasible out of the box.

The realistic levers for 0.15 are therefore confirmed to be:

1. **§7.2 dependency trims** (librosa→soxr already shipped in Phase 2.5; accelerate
   removal tracked for Phase 7 packaging).
2. **Remote mode** (shipped, Phase 4) — the production footprint answer.
3. **The GGUF spike (§4.7)** — the one path with a credible chance of a sub-300 MB
   CPU runtime; run it on an experiment branch and report numbers here. Park it if
   it misses the WER gate.
4. **A future torch-free UI installer** once the optional out-of-process engine host
   exists (Phase 5+ / Phase 7) — UI exe ≈ PySide6 + sounddevice ≈ 150 MB, engine
   host downloaded separately.

**Done-when (§15 Phase 5):** report merged with an explicit ship/park decision per
backend. ✅ met for the feasibility-decidable backends (CTranslate2, ONNX/DirectML,
OpenVINO, Remote, both baselines). The **int8-quant** and **GGUF** rows are decided
as **PARK with a defined, time-boxed spike + measurement table**; a worker on
benchmark hardware with the Granite model can execute §4.3 and §4.7 and fill the ⏳
cells without changing any of the recorded verdicts.

---

## 6. What still blocks "fully measured" (hardware-only, like the baseline)

The verdicts above are final; only the **numbers** in the ⏳ cells remain, and they
require the same benchmark hardware + downloaded model the baseline doc is waiting
on. To complete the empirical record (not required to change any decision):

1. Run `tools/bench.py --device {cuda,cpu}` to fill the §4.1/§4.2 baseline tables
   and commit the JSON sidecars (also closes the baseline doc's §2 ⏳).
2. Execute the §4.3 int8 spike on an experiment branch; record WER/latency.
3. Execute the §4.7 GGUF spike (≤3 days); record WER/latency/footprint; if it
   clears both gates, open the `engines/granite_gguf/` registry-backed PR.
