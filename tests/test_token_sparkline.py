"""Tests for the TokenSparkline custom-painted chart widget.

Validates edge cases: empty data, all-zero data, minimum sizes, and
that set_data triggers a repaint.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


def _qt_available() -> bool:
    try:
        from PySide6.QtWidgets import QApplication
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _qt_available(), reason="PySide6 not available")


@pytest.fixture
def sparkline():
    from speakeasy.developer_panel import TokenSparkline
    return TokenSparkline()


class TestSparklineEdgeCases:
    def test_sparkline_with_no_data_does_not_crash(self, sparkline):
        sparkline.set_data([])
        sparkline.repaint()  # should not raise

    def test_sparkline_handles_all_zero_data_without_division_error(self, sparkline):
        sparkline.set_data([0, 0, 0])
        sparkline.repaint()  # max_v = 0, fallback to 1.0 → no ZeroDivisionError

    def test_sparkline_single_point(self, sparkline):
        sparkline.set_data([42.0])
        sparkline.repaint()  # single point — no line drawn, no crash


class TestSparklineSizing:
    def test_sparkline_minimum_height(self, sparkline):
        assert sparkline.minimumHeight() == 70

    def test_sparkline_minimum_width(self, sparkline):
        assert sparkline.minimumWidth() == 200


class TestSparklineUpdate:
    def test_sparkline_set_data_triggers_update(self, sparkline):
        with patch.object(sparkline, "update") as mock_update:
            sparkline.set_data([1, 2, 3])
            mock_update.assert_called_once()
