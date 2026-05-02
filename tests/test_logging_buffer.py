"""Tests for the MainWindow log buffer that collects lines before the panel exists.

AST-level tests verify the buffering implementation structure.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MAIN_WINDOW_PATH = _REPO_ROOT / "speakeasy" / "main_window.py"


class TestLogBufferStructure:
    """AST-level checks on the _append_log / _flush_log_buffer pattern."""

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

    def test_log_buffer_initialized_in_init(self):
        src = self._method_source("__init__")
        assert "_log_buffer" in src

    def test_append_log_buffers_when_panel_none(self):
        src = self._method_source("_append_log")
        assert "_log_buffer.append(msg)" in src

    def test_buffer_caps_at_500_lines(self):
        src = self._method_source("_append_log")
        assert "500" in src
        assert "_log_buffer[-500:]" in src

    def test_append_log_routes_to_panel_when_open(self):
        src = self._method_source("_append_log")
        assert "self._dev_panel is not None" in src
        assert "logs_widget.log_text.append_log_line" in src

    def test_flush_log_buffer_clears_after_flush(self):
        src = self._method_source("_flush_log_buffer")
        assert "_log_buffer.clear()" in src

    def test_flush_called_on_panel_creation(self):
        src = self._method_source("_ensure_dev_panel")
        assert "_flush_log_buffer" in src
