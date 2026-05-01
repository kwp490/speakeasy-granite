# Test Suite Audit Report — Post Developer Panel Refactor

**Date:** 2026-04-26
**Test framework:** pytest 9.0.2 + pytest-qt 4.5.0 + pytest-cov 7.1.0 + pytest-mock 3.15.1
**Total tests:** 525 (362 original + 163 new) — **all passing**

---

## 1. Audit Table

| Test File | Bucket | Action |
|---|---|---|
| `test_audio.py` | STILL VALID | No changes. Tests core audio recording utilities. |
| `test_audio_utils.py` | STILL VALID | No changes. Tests resampling/ensure_16khz. |
| `test_build_naming.py` | STILL VALID | No changes. Tests build variant naming. |
| `test_cohere_transcribe.py` | STILL VALID | No changes. Tests Cohere engine transcription. |
| `test_config.py` | STILL VALID | No changes. Tests Settings save/load/validate (core logic untouched by refactor). |
| `test_engine_base.py` | STILL VALID | No changes. Tests ABC SpeechEngine interface. |
| `test_engine_load.py` | STILL VALID | No changes. Tests engine registry and availability. |
| `test_frozen_compat.py` | STILL VALID | No changes. Tests PyInstaller dist/ bundle structure. |
| `test_main_window_layout.py` | STILL VALID | No changes needed. Tests correctly assert that `_diag_toggle`/`_diag_content` are absent from `_build_ui`, that the gear button exists, and that bottom-row has no Settings/Pro Mode buttons. All AST-based checks reflect the refactored state. |
| `test_model_downloader.py` | STILL VALID | No changes. Tests HuggingFace model download logic. |
| `test_model_presence.py` | STILL VALID | No changes. Tests model presence detection. |
| `test_pro_preset.py` | STILL VALID | No changes. Tests ProPreset dataclass and built-in presets. |
| `test_pro_settings_dialog_ok.py` | STILL VALID | `pro_settings_dialog.py` still exists in the codebase (divergence from prompt which said it was deleted). All tests pass against the real module. |
| `test_professional_mode.py` | STILL VALID | No changes. AST checks on professional mode worker lifetime, preset architecture, and backward compatibility all pass. |
| `test_settings_dialog.py` | STILL VALID | No changes. Tests correctly verify SettingsWidget has no Professional Mode section and SettingsDialog is a thin shim. |
| `test_text_processor.py` | STILL VALID | No changes. Tests OpenAI text processing, sanitization, preset integration. |

---

## 2. Deletion Log

**No tests were deleted.** All 362 existing tests remain valid because:

- The existing tests already correctly assert the *absence* of removed UI (e.g., `_diag_toggle` not in `_build_ui`, no bottom-row Settings button).
- `pro_settings_dialog.py` was NOT actually deleted from the codebase (divergence from the prompt's description), so its tests remain valid.
- `_log_text` still exists on MainWindow as a hidden metric label for backward compatibility.
- All existing tests are either AST-level structural checks or business logic tests that don't depend on the refactored layout.

---

## 3. New Tests Added

| Test File | Test Count | Coverage Focus |
|---|---|---|
| `tests/conftest.py` | — (fixtures) | Shared fixtures: `temp_settings_dir`, `fresh_settings` |
| `tests/test_config_persistence.py` | 11 | Dev panel settings defaults, round-trip, forward-compat, validation |
| `tests/test_developer_panel_window.py` | 25 | DeveloperPanel + MainWindow AST structure: gear button, tabs, snap, close, log buffer, hotkey |
| `tests/test_developer_panel_live.py` | 25 | DeveloperPanel live widget: construction, tab navigation, close event, resize, snap, signal wiring, sparkline painting |
| `tests/test_settings_widget.py` | 17 | SettingsWidget auto-apply, risky-field Apply, reload signals, hotkey field |
| `tests/test_realtime_widget.py` | 16 | RealtimeDataWidget update methods, progress bars, audio meter, token FIFO, buttons |
| `tests/test_token_sparkline.py` | 6 | TokenSparkline edge cases, sizing, update trigger |
| `tests/test_logs_widget.py` | 6 | LogsWidget readonly, max block count, button signals, text append |
| `tests/test_logging_buffer.py` | 6 | MainWindow log buffer AST: init, buffering, cap, flush, routing |
| `tests/test_pro_mode_widget.py` | 22 | ProModeWidget structure + live: construction, enable toggle, disclosure callback, presets, API key, apply signals |
| `tests/test_hotkey_registration.py` | 8 | Hotkey defaults, parsing, HotkeyManager signals |
| `tests/test_metric_forwarding.py` | 6 | Metric forwarding AST: None guard, update_ram/vram/gpu calls |
| `tests/test_integration_full_flow.py` | 15 | Cross-phase AST regression: layout integrity, lazy creation, signal wiring, log buffer, pro mode toggle |
| **Total new** | **163** | |

---

## 4. Framework Decision

**Kept existing:** `pytest` (already configured in `pyproject.toml`).

**Added:**
- `pytest-qt >= 4.2` — Standard for PySide6 widget testing. Provides `qtbot` fixture for event loop management, signal waiting, and automatic QApplication creation. Essential for testing live widgets in the Developer Panel.
- `pytest-cov >= 4.0` — Coverage reporting via `--cov` flag.
- `pytest-mock >= 3.10` — `mocker` fixture for advanced mocking patterns.

These were added to `pyproject.toml` under `[project.optional-dependencies] dev`.

---

## 5. Coverage Summary

| Module | Stmts | Miss | Cover | Threshold Met? |
|---|---|---|---|---|
| `developer_panel.py` | 323 | 37 | **89%** | ✅ ≥ 70% |
| `pro_mode_widget.py` | 323 | 75 | **77%** | ✅ ≥ 70% |
| `settings_dialog.py` | 218 | 6 | **97%** | ✅ ≥ 70% |
| `config.py` | 93 | 2 | **98%** | ✅ ≥ 70% |
| `hotkeys.py` | 100 | 34 | **66%** | N/A (not new) |
| `main_window.py` | 1128 | 589 | **48%** | N/A (not new) |
| **Overall** | 3653 | 1250 | **66%** | — |

**Uncovered code in new modules:**
- `developer_panel.py` (11% uncovered): `paintEvent` body of TokenSparkline (hard to assert pixel output in offscreen mode), and the `_apply_stylesheet` method (large CSS string, not behavioral).
- `pro_mode_widget.py` (23% uncovered): `_on_new_preset`, `_on_duplicate_preset`, `_on_delete_preset` (require `QInputDialog.getText` mocking which is fragile), `_on_validate_api_key` network path, and `_on_validate_result`/`_on_validate_error` callbacks.

**No prior coverage baseline existed.** The numbers above serve as the new baseline.

---

## 6. Known Gaps

| Gap | Reason | Recommendation |
|---|---|---|
| Panel snapping geometry (exact pixel positions) | Offscreen platform does not support `frameGeometry()` accurately; window frame insets vary by platform. | Manual QA on real Windows desktop with multiple monitors. |
| Global hotkey OS-level registration | Requires a real HWND from a visible window on Windows; tests use `hwnd=0` which skips `RegisterHotKey`. | Manual QA: verify Ctrl+Alt+D toggles panel, and hotkey changes persist. |
| `MainWindow` full construction | Requires GPU monitor, audio hardware, engine loading, and keyring access. Heavy mocking is fragile and couples tests to internal implementation. | AST-level tests cover structural invariants. Manual QA for end-to-end flows. |
| Pro mode preset CRUD via UI dialogs | `QInputDialog.getText` and `QMessageBox.question` require modal dialog interaction that's fragile to mock in offscreen mode. | Manual QA: create, duplicate, delete presets. |
| Multi-monitor snap/resnap behavior | Cannot simulate multiple monitors in CI. | Manual QA on multi-monitor setup. |
| `_toggle_diagnostics` orphan method | Method references `_diag_content`/`_diag_toggle` attrs that no longer exist in `_build_ui`. Would crash if called at runtime. | Recommend removing the orphan method in a cleanup PR. |

---

## 7. Run Command

```bash
# Full suite with verbose output
uv run pytest tests/ -v

# With coverage report
uv run pytest tests/ -v --cov=speakeasy --cov-report=term-missing

# With HTML coverage report
uv run pytest tests/ -v --cov=speakeasy --cov-report=term-missing --cov-report=html
```

Environment: `QT_QPA_PLATFORM=offscreen` is set automatically by `tests/conftest.py`. No GPU, microphone, or OS hotkeys required.
