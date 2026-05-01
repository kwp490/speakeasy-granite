"""Tests for the LogsWidget in the Developer Panel.

Validates: read-only, max block count, button signals, text appending.
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
def logs_widget():
    from speakeasy.developer_panel import LogsWidget
    return LogsWidget()


class TestLogsWidgetProperties:
    def test_log_text_is_readonly(self, logs_widget):
        assert logs_widget.log_text.isReadOnly()

    def test_log_text_max_block_count_500(self, logs_widget):
        assert logs_widget.log_text.maximumBlockCount() == 500


class TestLogsWidgetButtons:
    def test_clear_button_emits_signal(self, logs_widget, qtbot):
        # Find the clear button by text
        from PySide6.QtWidgets import QPushButton
        clear_btns = [
            b for b in logs_widget.findChildren(QPushButton)
            if "Clear" in b.text()
        ]
        assert len(clear_btns) == 1
        with qtbot.waitSignal(logs_widget.clear_requested, timeout=1000):
            clear_btns[0].click()

    def test_copy_button_emits_signal(self, logs_widget, qtbot):
        from PySide6.QtWidgets import QPushButton
        copy_btns = [
            b for b in logs_widget.findChildren(QPushButton)
            if "Copy" in b.text()
        ]
        assert len(copy_btns) == 1
        with qtbot.waitSignal(logs_widget.copy_requested, timeout=1000):
            copy_btns[0].click()


class TestLogsWidgetTextAppend:
    def test_appending_lines_works(self, logs_widget):
        logs_widget.log_text.appendPlainText("hello")
        assert "hello" in logs_widget.log_text.toPlainText()

    def test_multiple_lines_append(self, logs_widget):
        logs_widget.log_text.appendPlainText("line1")
        logs_widget.log_text.appendPlainText("line2")
        text = logs_widget.log_text.toPlainText()
        assert "line1" in text
        assert "line2" in text
