# Task: Implement Phase 2.5 of the SpeakEasy AI Granite rearchitecture

You are continuing a multi-phase, incremental rearchitecture of the SpeakEasy AI
Granite app (a PySide6 Windows dictation app). Phases 0, 1, and 2 are complete.
Your job is **Phase 2.5 only** — the `librosa → soxr` resample swap and the
removal of the librosa/numba/llvmlite/scipy chain it drags in. Do not start
Phase 3 (settings schema) or Phase 4 (remote engine).

## Read these first (in the workspace)
- `docs/REARCHITECTURE-PROGRESS.md` — the handoff log. START HERE. It has the
  per-phase status, deviations, gotchas, and the "start here next" pointer that
  brought you to this phase. Note especially the Phase 2 entry and the **R-1
  manual GPU test still pending human verification** callout.
- `docs/REARCHITECTURE-PLAN.md` — the full plan. Phase 2.5 is the "two dependency
  cuts" win described in §2 (intro), §7.2 (librosa→soxr rationale, C-8/C-9),
  the quick-wins table in §12 (the `librosa.resample → soxr.resample` row), and
  the test-migration note in §12.2 (`test_audio_utils.py` — "Add soxr-vs-librosa
  equivalence test before the swap").
- The code you will build on:
  - `speakeasy/core/resample.py` — **already exists** (added in Phase 1). It is
    `ensure_16khz()` → `_resample()` which **prefers `soxr`, falls back to
    `librosa`**. This is the canonical resampler; Phase 2.5 routes everything here.
  - `speakeasy/engine/audio_utils.py` — `ensure_16khz()` still imports `librosa`
    directly (the duplicate, librosa-only path). `chunk_audio()` /
    `stitch_transcripts()` live here too and stay.
  - `speakeasy/main_window.py:927` `_resample_to_16k()` — lazily imports
    `from .engine.audio_utils import ensure_16khz` (the librosa path). Call sites
    at `:1068` (validate) and `:1228` (dictation loop).
  - `speakeasy/engine/base.py` — `SpeechEngine.transcribe()` also resamples on the
    engine side (C-9). After Phase 2 the UI already resamples to 16 kHz before
    calling the service, so the engine's internal call is a no-op at 16 kHz.

## Critical environment rule (will waste your time if ignored)
ALWAYS run tests with the project venv, never the bare `python` on PATH:
```powershell
& ".venv\Scripts\python.exe" -m pytest -q -n auto
```
The global Python has only numpy; `conftest.py` imports `main_window` (→ PySide6)
in an autouse fixture, so the bare interpreter fails the whole suite with
`ModuleNotFoundError: No module named 'PySide6'`. The `.venv` has all deps
(PySide6, torch, **soxr**, librosa). Baseline after Phase 2:
**640 passed, 3 skipped, 25 subtests**.

## Phase 2.5 objective
Make `soxr` the single resampling implementation across the whole app and drop
the librosa→numba→llvmlite→scipy chain (~150–300 MB onedir, plus a first-utterance
numba-JIT latency spike). After this phase, no app code path should call
`librosa.resample`, and importing the app with `librosa` absent must still work
(soxr-only). This is a **behavior-equivalence** change: transcription output must
be indistinguishable from the librosa baseline within tolerance.

## Order of operations (do equivalence FIRST, then swap, then remove)
1. **Equivalence test BEFORE changing any resample call.** Add
   `tests/test_resample_equivalence.py` (or extend `tests/test_audio_utils.py`)
   that loads a real signal (e.g. `speakeasy/assets/` validation audio if present,
   else a synthesized multi-tone sweep), resamples the SAME input with both
   `librosa.resample` and `soxr.resample` from a representative source rate
   (e.g. 44100 and 48000 → 16000), and asserts they match within tolerance
   (suggest: max abs error and/or RMS error thresholds, NOT exact equality —
   soxr and librosa use different kernels). Run it; record the tolerance you land
   on in the progress log. This test is the safety net for the swap.
2. **Route everything through `core/resample.py`.** Make `soxr` the primary path
   (it already is). Then collapse the duplicate:
   - `speakeasy/engine/audio_utils.py::ensure_16khz` should delegate to
     `speakeasy.core.resample.ensure_16khz` (or be replaced by re-export) so there
     is exactly one resampling implementation. Keep `chunk_audio` /
     `stitch_transcripts` where they are.
   - `speakeasy/main_window.py::_resample_to_16k` should import from
     `speakeasy.core.resample` instead of `speakeasy.engine.audio_utils`
     (removes the only reason the UI reaches into the engine package for audio).
   - Verify `SpeechEngine.transcribe()` (engine/base.py) resample path also uses
     the consolidated implementation; since the UI pre-resamples, confirm the
     engine call is a no-op at 16 kHz and stays correct if ever called at a
     non-16 kHz rate (it should now use soxr too).
3. **Drop librosa as a hard dependency** (validate, don't assume):
   - `pyproject.toml:33` — replace `"librosa>=0.10"` with `"soxr>=0.3"` (confirm
     the exact installed soxr version in the venv and pin a sane floor).
   - `core/resample.py` — once librosa is gone you may keep the `except ImportError`
     librosa fallback as defensive code OR drop it; decide and document. If you
     keep the fallback, leave librosa out of install_requires but tolerate its
     absence (the fallback simply never triggers).
   - **PyInstaller specs (R-2 still applies — be careful):**
     `speakeasy.spec:82` lists `'librosa'` in `hiddenimports`, and
     `speakeasy-cpu.spec` likely mirrors it. Add `'soxr'` to `hiddenimports` in
     BOTH specs. Only **remove** `'librosa'` from the specs if you have removed it
     from the actual import paths AND confirmed nothing transitively needs it.
     If unsure, add soxr and leave librosa for the Phase 7 packaging cleanup —
     document the decision.

## Tests to update (these encode the librosa coupling)
- `tests/test_frozen_ml_isolation.py::TestTransitiveDependenciesInSpec::test_librosa_in_hiddenimports`
  asserts `"librosa"` is in `speakeasy.spec` hiddenimports with the comment
  "librosa is required by the shared 16 kHz resampling path." After the swap this
  is false. Replace it with `test_soxr_in_hiddenimports` (and, if you removed
  librosa from the spec, assert librosa is **absent** / no longer required).
  Update the docstring rationale.
- `tests/test_audio_utils.py` (25 tests, resample/chunk/stitch) — the resample
  tests must still pass against the soxr-backed `ensure_16khz`. If any assert
  librosa-specific numerics, relax them to tolerance-based checks. Move/keep
  resample coverage pointed at `core/resample.py`.
- `tests/test_ml_import_isolation.py` / `test_frozen_ml_isolation.py` — `librosa`
  is in the `_BLOCKED` set. Those tests assert the UI/core import clean with
  librosa blocked; with soxr as primary they should already pass. Add an assertion
  (or new test) that `speakeasy.core.resample` / `main_window` import and that
  `ensure_16khz` **functions** with librosa blocked (soxr handles it) — this is
  the real proof librosa is no longer on the hot path.
- Grep the whole tree for `librosa` before you finish: `grep_search "librosa"`.
  Every remaining hit must be either (a) intentional defensive fallback, or
  (b) a test that explicitly documents the soxr-vs-librosa equivalence.

## Hard constraints / risks
- **Behavior equivalence is the bar.** Do not change chunking, trimming, dtype
  (`float32`), channel handling, or the 16 kHz target. The only change is the
  resampling kernel. The equivalence test gates this.
- **R-1 (CUDA DllMain hazard) is unrelated to this phase but still live.** Do not
  touch `DedicatedWorkerPool.warmup()` ordering or the engine-thread torch import.
  The R-1 manual Windows record-after-load GPU test from Phase 2 is **still
  pending human verification** — do not mark it done; carry the callout forward.
- **R-2 (PyInstaller may drop lazy imports).** soxr is imported lazily inside
  `core/resample.py::_resample`, so it MUST be in `hiddenimports` of both specs or
  the frozen build will fail at first resample. Removing librosa from the specs is
  only safe if no path imports it — when in doubt, defer librosa removal to
  Phase 7 and just add soxr now.
- **Frozen smoke test is the real proof for packaging changes**, and it cannot run
  in CI here. If you change `hiddenimports`, note in the progress log that a
  frozen onedir build + record-once smoke test is required human verification
  before release (same posture as the R-1 note).
- Do NOT wire in remote/server mode (Phase 4) or change `config.py` persistence /
  the settings schema (Phase 3). `settings.sample_rate` stays as-is; the UI keeps
  resampling to 16 kHz before calling `service.transcribe()`.

## Definition of done
1. A soxr-vs-librosa equivalence test exists and passes within a documented
   tolerance, and was added **before** the swap.
2. No app code path calls `librosa.resample`. `speakeasy.core.resample` is the
   single resampling implementation; `engine/audio_utils.ensure_16khz` and
   `main_window._resample_to_16k` both route through it (soxr primary).
3. `& ".venv\Scripts\python.exe" -c "import speakeasy.main_window"` succeeds, and
   an isolation test proves `ensure_16khz` works with `librosa` blocked (soxr
   path), not just that import succeeds.
4. Both `.spec` files list `'soxr'` in `hiddenimports`; the
   `test_*_in_hiddenimports` assertions are updated (soxr asserted; librosa
   assertion flipped or removed to match the actual spec state).
5. `pyproject.toml` declares `soxr` and no longer hard-requires `librosa` (unless
   you deliberately keep it as an optional fallback — document the choice).
6. Full suite green via `& ".venv\Scripts\python.exe" -m pytest -q -n auto`
   (≥ the Phase 2 baseline of 640 passed, minus any intentionally rewritten
   assertions, which must be replaced not deleted).
7. Update `docs/REARCHITECTURE-PROGRESS.md`: mark Phase 2.5 done with
   deliverables / deviations / gotchas (record the equivalence tolerance you used,
   and whether librosa was fully removed or kept as a fallback), and a
   "start here next" pointer to Phase 3. Re-state that the **R-1 GPU smoke test
   and (if specs changed) a frozen onedir smoke test remain pending human
   verification**.

## Working style
- Use a todo list; implement, don't just suggest. Read files before editing.
- Keep changes minimal and behavior-preserving — this is a dependency swap behind
  a stable boundary, not a redesign.
- Do the equivalence test FIRST. If soxr and librosa diverge beyond a sane
  tolerance on real audio, STOP and record it in the progress log rather than
  shipping a perceptible quality change.
- If you discover the plan is wrong (as OQ-1 was in Phase 0), record it in the
  progress log rather than silently following the plan.
