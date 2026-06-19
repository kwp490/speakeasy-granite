# Task: Implement Phase 2 of the SpeakEasy AI Granite rearchitecture

You are continuing a multi-phase, incremental rearchitecture of the SpeakEasy AI
Granite app (a PySide6 Windows dictation app). Phases 0 and 1 are complete. Your
job is **Phase 2 only**. Do not start Phase 2.5 or later.

## Read these first (in the workspace)
- `docs/REARCHITECTURE-PROGRESS.md` — the handoff log. START HERE. It has the
  per-phase status, deviations, gotchas, and a "start here next" pointer for Phase 2.
- `docs/REARCHITECTURE-PLAN.md` — the full plan. Phase 2 is defined in §15
  ("Phase 2 — Isolate heavy ML imports behind the boundary"). Also read §5
  (target architecture), §6 (engine boundary), and the C-1/C-3/C-5/C-6 rows of §4.
- The Phase 1 code you will build on: `speakeasy/core/` (contract.py, errors.py,
  model_source.py, resample.py), `speakeasy/engines/fake.py`,
  `speakeasy/services/inprocess.py`, and tests `tests/test_contract.py`,
  `tests/test_contract_conformance.py`, `tests/test_fake_engine.py`,
  `tests/test_model_source.py`.

## Critical environment rule (will waste your time if ignored)
ALWAYS run tests with the project venv, never the bare `python` on PATH:
```powershell
& ".venv\Scripts\python.exe" -m pytest -q -n auto
```
The global Python has only numpy; `conftest.py` imports `main_window` (→ PySide6)
in an autouse fixture, so the bare interpreter fails the whole suite with
`ModuleNotFoundError: No module named 'PySide6'`. The `.venv` has all deps
(PySide6, torch, soxr, librosa). Baseline after Phase 1: **633 passed, 3 skipped**.

## Phase 2 objective
The UI process must import **no torch/transformers/librosa at module scope**, and
`MainWindow` must talk only to a `speakeasy.core.contract.TranscriptionService`
(the Phase 1 `InProcessEngineService`), never to a concrete `SpeechEngine`, torch,
or transformers. In-process execution stays the default; this is purely about
moving heavy imports behind the boundary so the UI *can* run without torch installed.

## Scope — files to change (line numbers verified at current HEAD)
- `speakeasy/main_window.py`:
  - `:61` top-level `from .engine.granite_transcribe import GraniteTranscribeEngine` — remove.
  - `:275` `self._engine = GraniteTranscribeEngine()` — construct a
    `TranscriptionService` via a registry/service factory instead.
  - `:880-894` `_load_model` (calls `self._engine.load(self.settings.model_path, self.settings.device)`).
  - `:897-913` `_on_model_loaded` / `_actual_engine_device` (uses
    `getattr(self._engine, "actual_device", ...)`).
  - `:1015-1016` `self._engine.token_stats` 5-tuple → use `service.stats()` (`EngineStats`).
  - `:1197-1199` `getattr(self._engine, "configure_prompt_options", ...)` →
    pass `TranscriptionOptions` into `service.transcribe(...)` instead.
  - `:1969` `import torch` (CUDA power-resume probe) → move behind the service
    boundary (e.g. `service.health()` / a device probe), no torch import in main_window.
- `speakeasy/engine/__init__.py` → new `speakeasy/engines/registry.py`: map
  `name -> EngineDescriptor(factory, requires)` where the factory does the heavy
  import. Split `get_available_engines()` into `installed_engines()`
  (`importlib.util.find_spec`, no import) + model-file checks. Importing
  `speakeasy.engines` must NOT import torch.
- `speakeasy/engine/granite_transcribe.py`: move `import torch` and
  `from transformers import ...` (currently module-level, ~`:16-21`) into `load()`
  / method bodies. Keep behavior identical.
- Keep the Phase 1 `InProcessEngineService` as the adapter MainWindow uses.

## Tests
- ADD `tests/test_ml_import_isolation.py` (P0): run `python -c "import
  speakeasy.main_window"` (and `speakeasy.core.contract`, `speakeasy.services.*`)
  in a subprocess with a `sys.meta_path` blocker that raises on importing
  torch/transformers/librosa/accelerate, and assert success. Model the blocker on
  the existing one in `tests/test_contract.py::test_core_imports_without_ml_packages`.
- SPLIT `tests/test_frozen_compat.py` per plan §12.1: keep stdout/runtime-hook/Qt
  pruning checks; the torch/transformers/librosa hiddenimports assertions that
  currently encode the coupling need to move/relax. NOTE: `hiddenimports` in the
  `.spec` files must stay UNCHANGED this phase (PyInstaller still needs them for
  the now-lazy imports — that cleanup is Phase 7). Only adjust the *inverse* import
  assertions about module-scope imports.
- Granite engine tests must still pass with torch imported lazily (they run with
  torch available in the venv, so they should be unaffected; verify).

## Hard constraints / risks (from plan §16)
- **R-1 (CUDA DllMain hazard):** keep `DedicatedWorkerPool.warmup()` and its
  ordering; torch must import ON the engine thread (`_engine_pool`, a 1-thread
  pool), not the Qt main thread. See `speakeasy/workers.py` `warmup()` docstring.
  This is load-bearing — do not "simplify" it.
- **R-2 (PyInstaller drops lazy imports):** leave `speakeasy.spec` /
  `speakeasy-cpu.spec` `hiddenimports` unchanged this phase.
- **OQ-1 is RESOLVED: torchaudio IS REQUIRED** (Granite feature extractor calls
  `requires_backends(["torchaudio"])`). Do NOT remove torchaudio or touch the
  torch/torchaudio pairing test. The plan's §7.2 tentative "remove torchaudio" is
  superseded — see the Phase 0 entry in the progress log.
- The dictation loop (hotkey → record → transcribe → paste) must be behaviorally
  identical. Resampling stays where it is for now (the librosa→soxr swap is Phase 2.5).
- Do NOT wire in remote/server mode (Phase 4) or change the settings schema
  (Phase 3). Use the existing `settings.model_path`; you may wrap it in a
  `ManagedSource`/`LocalDirSource` when calling `service.load(source, device)`,
  but do not change `config.py` persistence.

## Definition of done
1. `& ".venv\Scripts\python.exe" -c "import speakeasy.main_window"` succeeds AND a
   new subprocess import-isolation test proves torch/transformers/librosa are not
   imported at `speakeasy.main_window` module scope.
2. Full suite green via `& ".venv\Scripts\python.exe" -m pytest -q -n auto`
   (≥ the Phase 1 baseline of 633 passed, minus any intentionally
   moved/rewritten frozen-compat assertions, which must be replaced not deleted).
3. `MainWindow` references no `GraniteTranscribeEngine`, no `torch`, no
   `configure_prompt_options`/`token_stats`/`actual_device` duck-typing — it uses
   the `TranscriptionService` contract.
4. Update `docs/REARCHITECTURE-PROGRESS.md`: mark Phase 2 done with
   deliverables/deviations/gotchas and a "start here next" pointer to Phase 2.5.
5. Note: I cannot do a real Windows GPU smoke test of record-after-load in CI;
   call out explicitly in the progress log that the R-1 manual test is pending
   human verification.

## Working style
- Use a todo list; implement, don't just suggest. Read files before editing.
- Keep changes minimal and behavior-preserving; this is a mechanical boundary
  move, not a redesign.
- If you discover the plan is wrong (as OQ-1 was), record it in the progress log
  rather than silently following the plan.
