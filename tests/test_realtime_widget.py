"""Tests for the RealtimeDataWidget in the Developer Panel.

Validates update methods, progress bar ranges, token history FIFO,
and button signal emissions.
"""

from __future__ import annotations

import pytest


def _qt_available() -> bool:
    try:
        from PySide6.QtWidgets import QApplication
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _qt_available(), reason="PySide6 not available")


@pytest.fixture
def realtime_widget():
    from speakeasy.developer_panel import RealtimeDataWidget
    return RealtimeDataWidget()


class TestEngineStatus:
    def test_engine_status_label_updates_on_call(self, realtime_widget):
        realtime_widget.update_engine_status("granite", "cuda", "Ready", "#22cc22")
        assert "granite" in realtime_widget._lbl_engine.text()
        assert "GPU" in realtime_widget._lbl_engine.text()
        assert "Ready" in realtime_widget._lbl_model_status.text()

    def test_engine_status_cpu_device(self, realtime_widget):
        realtime_widget.update_engine_status("granite", "cpu", "Loading", "#ffaa00")
        assert "CPU" in realtime_widget._lbl_engine.text()


class TestRAMProgressBar:
    def test_ram_progress_bar_updates_with_percent(self, realtime_widget):
        realtime_widget.update_ram(4.3, 6.3, 68.0)
        assert realtime_widget._pb_ram.value() == 68
        assert "4.3" in realtime_widget._lbl_ram.text()
        assert "6.3" in realtime_widget._lbl_ram.text()

    def test_ram_zero_total_resets(self, realtime_widget):
        realtime_widget.update_ram(0, 0, 0)
        assert realtime_widget._pb_ram.value() == 0
        assert "—" in realtime_widget._lbl_ram.text()


class TestVRAMProgressBar:
    def test_vram_progress_bar_updates_with_percent(self, realtime_widget):
        realtime_widget.update_vram(3.2, 7.8, 41.0)
        assert realtime_widget._pb_vram.value() == 41
        assert "3.2" in realtime_widget._lbl_vram.text()

    def test_vram_zero_total_resets(self, realtime_widget):
        realtime_widget.update_vram(0, 0, 0)
        assert realtime_widget._pb_vram.value() == 0
        assert "—" in realtime_widget._lbl_vram.text()


class TestGPULabel:
    def test_gpu_label_updates(self, realtime_widget):
        realtime_widget.update_gpu("NVIDIA RTX 4090")
        assert "NVIDIA RTX 4090" in realtime_widget._lbl_gpu_info.text()


class TestTokenLabels:
    def test_token_labels_format_correctly(self, realtime_widget):
        realtime_widget.update_tokens(142.0, 1243, 340)
        assert "142" in realtime_widget._lbl_tok_rate.text()
        assert "tok/s" in realtime_widget._lbl_tok_rate.text()
        assert "1,243" in realtime_widget._lbl_tok_in.text()
        assert "340" in realtime_widget._lbl_tok_out.text()


class TestTokenHistory:
    def test_token_history_appends_and_caps_at_60(self, realtime_widget):
        for i in range(80):
            realtime_widget.update_tokens(float(i), i, i)
        assert len(realtime_widget._llm_tok_history) == 60

    def test_token_history_drops_oldest_first(self, realtime_widget):
        for i in range(70):
            realtime_widget.update_tokens(float(i), i, i)
        # 70 items added, capped to last 60 → first stored = 10
        assert realtime_widget._llm_tok_history[0] == 10.0


class TestRealtimeButtons:
    def test_reload_model_button_emits_signal(self, realtime_widget, qtbot):
        with qtbot.waitSignal(realtime_widget.reload_model_requested, timeout=1000):
            realtime_widget._btn_reload.click()

    def test_validate_button_emits_signal(self, realtime_widget, qtbot):
        with qtbot.waitSignal(realtime_widget.validate_requested, timeout=1000):
            realtime_widget._btn_validate.click()
