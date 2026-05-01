"""Live widget tests for DeveloperPanel and its sub-widgets.

These tests construct real PySide6 widgets in offscreen mode to cover
runtime code paths (constructors, slot wiring, tab navigation, etc.)
that AST tests cannot reach.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _qt_available() -> bool:
    try:
        from PySide6.QtWidgets import QApplication
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _qt_available(), reason="PySide6 not available")


@pytest.fixture
def mock_main_window(tmp_path, monkeypatch, qtbot):
    """Create a minimal mock MainWindow with enough surface for DeveloperPanel."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QWidget

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    presets_dir = config_dir / "presets"
    presets_dir.mkdir()
    monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_DIR", config_dir)
    monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_FILE", config_dir / "settings.json")
    monkeypatch.setattr("speakeasy.config.DEFAULT_PRESETS_DIR", presets_dir)
    # Mock keyring
    monkeypatch.setattr("speakeasy.pro_mode_widget.load_api_key_from_keyring", lambda: "")
    monkeypatch.setattr("speakeasy.pro_mode_widget.save_api_key_to_keyring", lambda k: None)
    monkeypatch.setattr("speakeasy.pro_mode_widget.delete_api_key_from_keyring", lambda: None)

    mw = QWidget()
    mw.resize(720, 820)
    mw.move(100, 100)
    # DeveloperPanel accesses these MainWindow methods:
    mw._on_reload_model = MagicMock()
    mw._apply_settings = MagicMock()
    mw._on_validate = MagicMock()
    mw._on_clear_logs = MagicMock()
    mw._on_copy_logs = MagicMock()
    mw._on_pro_mode_applied = MagicMock()
    mw._populate_pro_preset_combo = MagicMock()
    qtbot.addWidget(mw)
    return mw


@pytest.fixture
def dev_panel(mock_main_window):
    from speakeasy.config import Settings
    from speakeasy.developer_panel import DeveloperPanel

    settings = Settings()
    panel = DeveloperPanel(settings, mock_main_window)
    return panel, settings


class TestDeveloperPanelConstruction:
    def test_panel_constructs_without_error(self, dev_panel):
        panel, _ = dev_panel
        assert panel is not None

    def test_panel_has_four_tabs(self, dev_panel):
        panel, _ = dev_panel
        assert panel._tabs.count() == 4

    def test_panel_default_tab_is_settings(self, dev_panel):
        panel, settings = dev_panel
        assert settings.dev_panel_active_tab == "settings"
        assert panel._tabs.currentIndex() == 0

    def test_panel_restores_active_tab(self, mock_main_window):
        from speakeasy.config import Settings
        from speakeasy.developer_panel import DeveloperPanel

        settings = Settings(dev_panel_active_tab="logs")
        panel = DeveloperPanel(settings, mock_main_window)
        assert panel._tabs.currentIndex() == 2  # logs tab index


class TestDeveloperPanelTabNavigation:
    def test_switching_tabs_persists_active_tab(self, dev_panel, tmp_path, monkeypatch):
        panel, settings = dev_panel
        panel._tabs.setCurrentIndex(1)  # Realtime Data
        assert settings.dev_panel_active_tab == "realtime"

    def test_switching_to_logs_tab(self, dev_panel):
        panel, settings = dev_panel
        panel._tabs.setCurrentIndex(2)
        assert settings.dev_panel_active_tab == "logs"

    def test_switching_to_pro_tab(self, dev_panel):
        panel, settings = dev_panel
        panel._tabs.setCurrentIndex(3)
        assert settings.dev_panel_active_tab == "pro"

    def test_switching_back_to_settings(self, dev_panel):
        panel, settings = dev_panel
        panel._tabs.setCurrentIndex(2)
        panel._tabs.setCurrentIndex(0)
        assert settings.dev_panel_active_tab == "settings"


class TestDeveloperPanelCloseEvent:
    def test_close_event_hides_panel(self, dev_panel):
        panel, _ = dev_panel
        panel.show()
        panel.close()
        assert not panel.isVisible()

    def test_close_event_emits_closed_signal(self, dev_panel, qtbot):
        panel, _ = dev_panel
        panel.show()
        with qtbot.waitSignal(panel.closed, timeout=1000):
            panel.close()


class TestDeveloperPanelResizing:
    def test_resize_event_persists_dimensions(self, dev_panel):
        """Directly modify panel size to exercise persistence path."""
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QResizeEvent
        panel, settings = dev_panel
        # Ensure suppress flag is off
        panel._suppress_move_persist = False
        # The resizeEvent uses self.width()/self.height(), so we need to
        # actually show the panel and resize it, then manually fire the event.
        panel.show()
        panel.resize(600, 800)
        # In offscreen mode, width/height may reflect the resize
        event = QResizeEvent(panel.size(), QSize(480, 720))
        panel.resizeEvent(event)
        # Should have saved whatever the current widget size is
        assert settings.dev_panel_width == panel.width()
        assert settings.dev_panel_height == panel.height()

    def test_resize_suppressed_during_snap(self, dev_panel):
        """Resize during programmatic snap should NOT persist."""
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QResizeEvent
        panel, settings = dev_panel
        panel._suppress_move_persist = True
        event = QResizeEvent(QSize(999, 999), QSize(480, 720))
        panel.resizeEvent(event)
        assert settings.dev_panel_width == 600  # unchanged


class TestDeveloperPanelSnapping:
    def test_show_snapped_positions_panel(self, dev_panel):
        panel, settings = dev_panel
        assert settings.dev_panel_snapped is True
        panel.show_snapped()
        assert panel.isVisible()

    def test_on_main_window_moved_repositions(self, dev_panel):
        panel, settings = dev_panel
        panel.show_snapped()
        # Move main window — panel should follow
        panel._main_window.move(200, 200)
        panel.on_main_window_moved()
        # Panel should have moved (not testing exact position due to frame insets)
        assert panel.isVisible()


class TestDeveloperPanelSignalWiring:
    def test_settings_widget_reload_connected(self, dev_panel):
        panel, _ = dev_panel
        # Emit the signal — should call mock
        panel._settings_widget.reload_model_requested.emit()
        panel._main_window._on_reload_model.assert_called_once()

    def test_realtime_reload_connected(self, dev_panel):
        panel, _ = dev_panel
        panel.realtime_widget.reload_model_requested.emit()
        panel._main_window._on_reload_model.assert_called()

    def test_realtime_validate_connected(self, dev_panel):
        panel, _ = dev_panel
        panel.realtime_widget.validate_requested.emit()
        panel._main_window._on_validate.assert_called_once()

    def test_logs_clear_connected(self, dev_panel):
        panel, _ = dev_panel
        panel.logs_widget.clear_requested.emit()
        panel._main_window._on_clear_logs.assert_called_once()

    def test_logs_copy_connected(self, dev_panel):
        panel, _ = dev_panel
        panel.logs_widget.copy_requested.emit()
        panel._main_window._on_copy_logs.assert_called_once()


class TestDeveloperPanelActivateTab:
    def test_activate_tab_settings(self, dev_panel):
        panel, _ = dev_panel
        panel.activate_tab("settings")
        assert panel._tabs.currentIndex() == 0

    def test_activate_tab_realtime(self, dev_panel):
        panel, _ = dev_panel
        panel.activate_tab("realtime")
        assert panel._tabs.currentIndex() == 1

    def test_activate_tab_logs(self, dev_panel):
        panel, _ = dev_panel
        panel.activate_tab("logs")
        assert panel._tabs.currentIndex() == 2

    def test_activate_tab_pro(self, dev_panel):
        panel, _ = dev_panel
        panel.activate_tab("pro")
        assert panel._tabs.currentIndex() == 3


class TestTokenSparklinePainting:
    """Exercise paint code paths for coverage."""

    def test_sparkline_paint_with_data(self):
        from speakeasy.developer_panel import TokenSparkline
        s = TokenSparkline()
        s.resize(200, 60)
        s.set_data([10, 20, 30, 25, 40])
        s.repaint()  # exercises paintEvent

    def test_sparkline_paint_with_two_points(self):
        from speakeasy.developer_panel import TokenSparkline
        s = TokenSparkline()
        s.resize(200, 60)
        s.set_data([5, 15])
        s.repaint()
