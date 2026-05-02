"""Tests for the Developer Panel window behaviour.

Uses the DeveloperPanel directly (not via MainWindow) for isolated testing.
Some tests use AST inspection for layout verification since constructing
a full MainWindow requires heavy mocking of engine/audio subsystems.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MAIN_WINDOW_PATH = _REPO_ROOT / "speakeasy" / "main_window.py"
_DEV_PANEL_PATH = _REPO_ROOT / "speakeasy" / "developer_panel.py"


# ═══════════════════════════════════════════════════════════════════════════════
# AST-level tests — no Qt needed
# ═══════════════════════════════════════════════════════════════════════════════


class TestDevPanelLayoutAST:
    """Verify _build_ui structure matches the refactored layout via AST."""

    @classmethod
    def setup_class(cls):
        cls._mw_source = _MAIN_WINDOW_PATH.read_text(encoding="utf-8")
        cls._mw_tree = ast.parse(cls._mw_source, filename="main_window.py")
        cls._mw_class = None
        for node in ast.walk(cls._mw_tree):
            if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
                cls._mw_class = node
                break
        assert cls._mw_class is not None

    def _mw_method_source(self, method_name: str) -> str:
        for node in ast.walk(self._mw_class):
            if isinstance(node, ast.FunctionDef) and node.name == method_name:
                return ast.get_source_segment(self._mw_source, node) or ""
        pytest.fail(f"Method '{method_name}' not found in MainWindow")

    def _mw_method_names(self):
        return [n.name for n in ast.walk(self._mw_class) if isinstance(n, ast.FunctionDef)]

    # ── Panel not created at startup ─────────────────────────────────────────

    def test_dev_panel_initialized_none(self):
        src = self._mw_method_source("__init__")
        assert "self._dev_panel" in src
        # Initial value must be None (lazy creation)
        assert "_dev_panel: Optional" in self._mw_source or "_dev_panel = None" in src

    # ── Gear button exists ───────────────────────────────────────────────────

    def test_gear_button_created_in_build_ui(self):
        src = self._mw_method_source("_build_ui")
        assert "self._btn_dev_panel" in src

    def test_gear_button_is_checkable(self):
        src = self._mw_method_source("_build_ui")
        assert "setCheckable(True)" in src

    def test_gear_button_uses_compact_height(self):
        src = self._mw_method_source("_build_ui")
        assert "setMinimumSize(Size.GEAR_BUTTON, Size.BUTTON_HEIGHT_PRIMARY)" in src
        assert "setMaximumSize(16777215, Size.BUTTON_HEIGHT_PRIMARY)" in src

    # ── Toggle method exists ─────────────────────────────────────────────────

    def test_on_toggle_dev_panel_method_exists(self):
        assert "_on_toggle_dev_panel" in self._mw_method_names()

    def test_on_dev_panel_closed_method_exists(self):
        assert "_on_dev_panel_closed" in self._mw_method_names()

    # ── Panel persists state ─────────────────────────────────────────────────

    def test_toggle_saves_settings(self):
        """_on_toggle_dev_panel must call self.settings.save()."""
        src = self._mw_method_source("_on_toggle_dev_panel")
        assert "self.settings.save()" in src

    def test_toggle_sets_dev_panel_open(self):
        src = self._mw_method_source("_on_toggle_dev_panel")
        assert "self.settings.dev_panel_open" in src

    # ── Removed diagnostics ──────────────────────────────────────────────────

    def test_no_diag_toggle_in_build_ui(self):
        src = self._mw_method_source("_build_ui")
        assert "_diag_toggle" not in src

    def test_no_diag_content_in_build_ui(self):
        src = self._mw_method_source("_build_ui")
        assert "_diag_content" not in src

    # ── Bottom row only Quit ─────────────────────────────────────────────────

    def test_no_settings_button_in_build_ui(self):
        src = self._mw_method_source("_build_ui")
        # No "⚙️ Settings" or "Settings" button text in the bottom row
        assert "Settings" not in src.split("bottom_row")[1] if "bottom_row" in src else True

    def test_no_pro_mode_settings_button_in_build_ui(self):
        src = self._mw_method_source("_build_ui")
        assert "Pro Mode Settings" not in src

    # ── Log buffer ───────────────────────────────────────────────────────────

    def test_log_buffer_initialized(self):
        src = self._mw_method_source("__init__")
        assert "_log_buffer" in src

    def test_flush_log_buffer_method_exists(self):
        assert "_flush_log_buffer" in self._mw_method_names()

    # ── Hotkey connection ────────────────────────────────────────────────────

    def test_dev_panel_hotkey_connected(self):
        src = self._mw_method_source("_connect_hotkeys")
        assert "dev_panel_toggle_requested" in src
        assert "_on_toggle_dev_panel" in src


# ═══════════════════════════════════════════════════════════════════════════════
# DeveloperPanel structure tests (AST)
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeveloperPanelStructureAST:
    """AST checks on DeveloperPanel class."""

    @classmethod
    def setup_class(cls):
        cls._source = _DEV_PANEL_PATH.read_text(encoding="utf-8")
        cls._tree = ast.parse(cls._source, filename="developer_panel.py")
        cls._dp_class = None
        for node in ast.walk(cls._tree):
            if isinstance(node, ast.ClassDef) and node.name == "DeveloperPanel":
                cls._dp_class = node
                break
        assert cls._dp_class is not None

    def _method_source(self, method_name: str) -> str:
        for node in ast.walk(self._dp_class):
            if isinstance(node, ast.FunctionDef) and node.name == method_name:
                return ast.get_source_segment(self._source, node) or ""
        pytest.fail(f"Method '{method_name}' not found in DeveloperPanel")

    def _method_names(self):
        return [n.name for n in ast.walk(self._dp_class) if isinstance(n, ast.FunctionDef)]

    def test_panel_has_five_tabs(self):
        src = self._method_source("_build_ui")
        assert src.count("addTab") == 5

    def test_close_event_hides_instead_of_destroying(self):
        src = self._method_source("closeEvent")
        assert "event.ignore()" in src
        assert "self.hide()" in src

    def test_tab_change_persists(self):
        src = self._method_source("_on_tab_changed")
        assert "self.settings.dev_panel_active_tab" in src
        assert "self.settings.save()" in src

    def test_resize_persists(self):
        src = self._method_source("resizeEvent")
        assert "dev_panel_width" in src
        assert "dev_panel_height" in src
        assert "self.settings.save()" in src

    def test_snap_threshold_defined(self):
        assert "SNAP_THRESHOLD_PX" in self._source

    def test_snap_to_main_method_exists(self):
        assert "_snap_to_main" in self._method_names()

    def test_on_main_window_moved_exists(self):
        assert "on_main_window_moved" in self._method_names()

    def test_show_snapped_method_exists(self):
        assert "show_snapped" in self._method_names()

    def test_move_event_tracks_snap(self):
        src = self._method_source("moveEvent")
        assert "SNAP_THRESHOLD_PX" in src
        assert "self._snapped" in src
