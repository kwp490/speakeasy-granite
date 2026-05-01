"""Tests for metric forwarding from MainWindow to the Developer Panel.

AST-level tests verify the forwarding logic in _on_metrics_result
routes data to the panel's RealtimeDataWidget when the panel exists.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MAIN_WINDOW_PATH = _REPO_ROOT / "speakeasy" / "main_window.py"


class TestMetricForwarding:
    """AST checks on _on_metrics_result forwarding to panel."""

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

    def test_metrics_result_forwards_to_panel(self):
        src = self._method_source("_on_metrics_result")
        assert "self._dev_panel is not None" in src
        assert "realtime_widget" in src

    def test_metrics_result_calls_update_ram(self):
        src = self._method_source("_on_metrics_result")
        assert "rw.update_ram(" in src

    def test_metrics_result_calls_update_vram(self):
        src = self._method_source("_on_metrics_result")
        assert "rw.update_vram(" in src

    def test_metrics_result_calls_update_gpu(self):
        src = self._method_source("_on_metrics_result")
        assert "rw.update_gpu(" in src

    def test_metrics_no_crash_when_panel_none(self):
        """The forwarding block must be guarded by 'if self._dev_panel is not None'."""
        src = self._method_source("_on_metrics_result")
        # The guard must appear BEFORE the forwarding calls
        guard_pos = src.find("self._dev_panel is not None")
        rw_pos = src.find("rw = self._dev_panel.realtime_widget")
        assert guard_pos < rw_pos

    def test_model_status_forwards_to_panel(self):
        """_set_model_status should forward engine status to panel when open."""
        src = self._method_source("_set_model_status")
        assert "self._dev_panel is not None" in src or "realtime_widget" in src
