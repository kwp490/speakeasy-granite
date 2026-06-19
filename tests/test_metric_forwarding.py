"""Tests for metric forwarding to the Developer Panel.

The metrics-handling logic moved out of MainWindow into
``speakeasy.ui.metrics_bridge.MetricsBridge`` (Phase 6, plan §9).  The behavior
tests below drive the bridge directly with fake metrics and a fake main window,
verifying it updates the status strip and forwards to the panel's
RealtimeDataWidget only when the panel exists.  One AST check remains for
``_set_model_status``, which still lives on MainWindow.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MAIN_WINDOW_PATH = _REPO_ROOT / "speakeasy" / "main_window.py"
_MODEL_CONTROLLER_PATH = _REPO_ROOT / "speakeasy" / "ui" / "model_controller.py"


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

    def test_model_status_forwards_to_panel(self):
        """_set_model_status should forward engine status to panel when open."""
        # _set_model_status moved to ModelController (Phase 6, plan §9).
        src = _MODEL_CONTROLLER_PATH.read_text(encoding="utf-8")
        assert "self._dev_panel is not None" in src or "realtime_widget" in src


# ── MetricsBridge behavior tests ──────────────────────────────────────────────

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject  # noqa: E402

from speakeasy.ui.metrics_bridge import MetricsBridge  # noqa: E402


class _FakeMainWindow(QObject):
    """Minimal QObject stand-in exposing the attributes MetricsBridge touches."""

    def __init__(self, *, dev_panel=None) -> None:
        super().__init__()
        self._lbl_ram = MagicMock()
        self._pb_ram = MagicMock()
        self._lbl_vram = MagicMock()
        self._pb_vram = MagicMock()
        self._lbl_gpu_info = MagicMock()
        self._dev_panel = dev_panel
        self._text_processor = SimpleNamespace(token_stats=(1.0, 2, 3, 4))
        self._service = SimpleNamespace(
            stats=lambda: SimpleNamespace(
                tokens_per_second=5.0,
                total_tokens=6,
                total_audio_seconds=7.0,
                realtime_factor=8.0,
                inference_count=9,
            )
        )


def _metrics(*, ram_total=16.0, vram_total=8.0):
    gpu = SimpleNamespace(
        vram_total_gb=vram_total,
        vram_used_gb=2.0,
        vram_percent=25.0,
        name="Test GPU",
        temperature_c=50,
    )
    return SimpleNamespace(
        ram_used_gb=4.0,
        ram_total_gb=ram_total,
        ram_percent=25.0,
        gpu=gpu,
    )


def _make_dev_panel():
    return SimpleNamespace(realtime_widget=MagicMock())


def test_updates_main_window_ram_strip():
    mw = _FakeMainWindow()
    bridge = MetricsBridge(mw)
    bridge.on_metrics_result(_metrics())
    mw._lbl_ram.setText.assert_called()
    mw._pb_ram.setValue.assert_called_with(25)


def test_ram_strip_shows_placeholder_when_total_zero():
    mw = _FakeMainWindow()
    bridge = MetricsBridge(mw)
    bridge.on_metrics_result(_metrics(ram_total=0.0))
    mw._lbl_ram.setText.assert_called_with("RAM: —")
    mw._pb_ram.setValue.assert_called_with(0)


def test_no_forwarding_when_panel_none():
    mw = _FakeMainWindow(dev_panel=None)
    bridge = MetricsBridge(mw)
    # Must not raise even though there is no panel to forward to.
    bridge.on_metrics_result(_metrics())


def test_forwards_ram_to_panel_when_open():
    dev_panel = _make_dev_panel()
    mw = _FakeMainWindow(dev_panel=dev_panel)
    bridge = MetricsBridge(mw)
    bridge.on_metrics_result(_metrics())
    dev_panel.realtime_widget.update_ram.assert_called_once()


def test_forwards_tokens_and_asr_stats_to_panel():
    dev_panel = _make_dev_panel()
    mw = _FakeMainWindow(dev_panel=dev_panel)
    bridge = MetricsBridge(mw)
    bridge.on_metrics_result(_metrics())
    dev_panel.realtime_widget.update_tokens.assert_called_once_with(1.0, 2, 3, seq=4)
    dev_panel.realtime_widget.update_asr_tokens.assert_called_once_with(
        5.0, 6, 7.0, 8.0, seq=9
    )


def test_forwards_vram_when_gpu_variant(monkeypatch):
    monkeypatch.setattr("speakeasy.ui.metrics_bridge.VARIANT", "gpu")
    dev_panel = _make_dev_panel()
    mw = _FakeMainWindow(dev_panel=dev_panel)
    bridge = MetricsBridge(mw)
    bridge.on_metrics_result(_metrics(vram_total=8.0))
    dev_panel.realtime_widget.update_vram.assert_called_once_with(2.0, 8.0, 25.0)
    dev_panel.realtime_widget.update_gpu.assert_called_once()


def test_bridge_is_parented_to_main_window():
    mw = _FakeMainWindow()
    bridge = MetricsBridge(mw)
    assert bridge.parent() is mw
