"""Cross-phase integration / regression tests.

AST-level tests that verify multiple refactor phases work together.
These run without Qt or GPU, checking source-level invariants.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MAIN_WINDOW_PATH = _REPO_ROOT / "speakeasy" / "main_window.py"
_DEV_PANEL_PATH = _REPO_ROOT / "speakeasy" / "developer_panel.py"
_SETTINGS_DIALOG_PATH = _REPO_ROOT / "speakeasy" / "settings_dialog.py"


class TestIntegrationMainWindowLayout:
    """Verify the main window's post-refactor layout integrity."""

    @classmethod
    def setup_class(cls):
        cls._source = _MAIN_WINDOW_PATH.read_text(encoding="utf-8")
        cls._tree = ast.parse(cls._source, filename="main_window.py")
        cls._mw_class = None
        for node in ast.walk(cls._tree):
            if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
                cls._mw_class = node
                break
        assert cls._mw_class is not None

    def _method_source(self, name: str) -> str:
        for node in ast.walk(self._mw_class):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.get_source_segment(self._source, node) or ""
        pytest.fail(f"Method '{name}' not found in MainWindow")

    def _method_names(self):
        return [n.name for n in ast.walk(self._mw_class) if isinstance(n, ast.FunctionDef)]

    # ── Phase 1 + 2: Record row and gear button ─────────────────────────────

    def test_record_and_gear_in_same_layout(self):
        src = self._method_source("_build_ui")
        # Both must be in record_row layout
        assert "record_row.addWidget(self._btn_record" in src
        assert "record_row.addWidget(self._btn_dev_panel)" in src

    # ── Phase 2: Dev panel is lazily created ─────────────────────────────────

    def test_panel_created_lazily_on_toggle(self):
        src = self._method_source("_ensure_dev_panel")
        assert "if self._dev_panel is None:" in src
        assert "DeveloperPanel(" in src

    # ── Phase 3: Panel wires settings_applied signal ─────────────────────────

    def test_panel_wires_settings_applied_to_main_window(self):
        dp_source = _DEV_PANEL_PATH.read_text(encoding="utf-8")
        assert "settings_applied.connect(self._main_window._apply_settings)" in dp_source

    def test_panel_wires_reload_model_to_main_window(self):
        dp_source = _DEV_PANEL_PATH.read_text(encoding="utf-8")
        assert "reload_model_requested.connect(self._main_window._model_controller._on_reload_model)" in dp_source

    # ── Phase 4 / 6: Metric forwarding lives in MetricsBridge ────────────────

    def test_metrics_forwarding_guarded_by_none_check(self):
        from speakeasy.ui import metrics_bridge as mb
        src = (Path(mb.__file__)).read_text(encoding="utf-8")
        guard_pos = src.find("mw._dev_panel is not None")
        update_pos = src.find("rw.update_ram(")
        assert guard_pos != -1
        assert guard_pos < update_pos

    # ── Phase 5: Log buffer integration ──────────────────────────────────────

    def test_panel_creation_flushes_log_buffer(self):
        src = self._method_source("_ensure_dev_panel")
        assert "_flush_log_buffer()" in src

    # ── Main-window transcription mode controls ────────────────────────────

    def test_no_chk_professional(self):
        src = self._method_source("_build_ui")
        assert "self._chk_professional" not in src

    def test_main_profile_selector_exists(self):
        src = self._method_source("_build_ui")
        assert "self._chk_transcription_mode" in src
        assert "self._combo_pro_preset" in src
        assert "_on_transcription_mode_toggled" in src
        assert "_on_main_profile_selected" in src

    def test_missing_api_key_routes_to_providers_tab(self):
        src = "\n".join(
            self._method_source(name) for name in (
                "_on_main_profile_selected",
                "_on_open_ai_providers",
            )
        )
        assert "not self._api_key" in src
        # AI Providers folded into the AI Writing Profiles tab (Phase 6).
        assert "TAB_PRO" in src
        assert "activate_tab(TAB_PRO)" in src

    def test_no_on_professional_toggled(self):
        assert "_on_professional_toggled" not in self._method_names()

    # ── No regressions ───────────────────────────────────────────────────────

    def test_quit_button_exists_in_bottom_row(self):
        src = self._method_source("_build_ui")
        assert 'QPushButton("Quit")' in src or "Quit" in src

    def test_history_section_exists(self):
        """History must be accessible via the developer panel's HistoryWidget."""
        dp_source = _DEV_PANEL_PATH.read_text(encoding="utf-8")
        assert "HistoryWidget" in dp_source
        assert "history_widget" in dp_source

    def test_engine_pool_single_thread(self):
        src = self._method_source("__init__")
        assert "setMaxThreadCount(1)" in src
        assert "setExpiryTimeout(-1)" in src
