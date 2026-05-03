"""Tests for new developer-panel Settings fields in config.py.

Covers: defaults, save/load round-trip, forward-compat, and validation
for the six new dev_panel_* fields + hotkey_dev_panel.
"""

import json
from pathlib import Path

import pytest

from speakeasy.config import Settings


class TestDevPanelFieldDefaults:
    """Instantiate Settings() and verify all new fields have documented defaults."""

    def test_dev_panel_open_default_false(self):
        assert Settings().dev_panel_open is False

    def test_dev_panel_active_tab_default_settings(self):
        assert Settings().dev_panel_active_tab == "settings"

    def test_dev_panel_width_default_629(self):
        assert Settings().dev_panel_width == 629

    def test_dev_panel_height_default_880(self):
        assert Settings().dev_panel_height == 880

    def test_dev_panel_snapped_default_true(self):
        assert Settings().dev_panel_snapped is True

    def test_hotkey_dev_panel_default(self):
        assert Settings().hotkey_dev_panel == "ctrl+alt+d"


class TestDevPanelRoundTrip:
    """Save and load all dev panel fields, verify they round-trip."""

    def test_settings_save_load_roundtrip_includes_dev_panel_fields(self, tmp_path):
        path = tmp_path / "settings.json"
        s = Settings(
            dev_panel_open=True,
            dev_panel_active_tab="logs",
            dev_panel_width=629,
            dev_panel_height=900,
            dev_panel_snapped=False,
            hotkey_dev_panel="ctrl+shift+d",
        )
        s.save(path)
        loaded = Settings.load(path)

        assert loaded.dev_panel_open is True
        assert loaded.dev_panel_active_tab == "logs"
        assert loaded.dev_panel_width == 629
        assert loaded.dev_panel_height == 900
        assert loaded.dev_panel_snapped is False
        assert loaded.hotkey_dev_panel == "ctrl+shift+d"


class TestForwardCompat:
    """Old settings.json without new keys should fill defaults gracefully."""

    def test_load_old_settings_file_without_new_keys_uses_defaults(self, tmp_path):
        path = tmp_path / "settings.json"
        old_data = {"engine": "granite", "auto_copy": False}
        path.write_text(json.dumps(old_data), encoding="utf-8")

        loaded = Settings.load(path)

        # Old field honoured
        assert loaded.auto_copy is False
        # New fields get defaults
        assert loaded.dev_panel_open is False
        assert loaded.dev_panel_active_tab == "settings"
        assert loaded.dev_panel_width == 629
        assert loaded.dev_panel_height == 880
        assert loaded.dev_panel_snapped is True
        assert loaded.hotkey_dev_panel == "ctrl+alt+d"


class TestDevPanelValidation:
    """Settings.validate() must clamp invalid dev panel values."""

    def test_validate_clamps_invalid_active_tab(self):
        s = Settings(dev_panel_active_tab="garbage")
        s.validate()
        assert s.dev_panel_active_tab == "settings"

    def test_validate_clamps_undersized_width(self):
        s = Settings(dev_panel_width=10)
        s.validate()
        assert s.dev_panel_width == 629

    def test_validate_clamps_legacy_width_480(self):
        s = Settings(dev_panel_width=480)
        s.validate()
        assert s.dev_panel_width == 629

    def test_validate_clamps_undersized_height(self):
        s = Settings(dev_panel_height=10)
        s.validate()
        assert s.dev_panel_height == 880

    @pytest.mark.parametrize("tab", ["settings", "advanced", "realtime", "logs", "pro", "history"])
    def test_validate_accepts_all_valid_tab_keys(self, tab):
        s = Settings(dev_panel_active_tab=tab)
        s.validate()
        assert s.dev_panel_active_tab == tab

    def test_validate_accepts_valid_dimensions(self):
        s = Settings(dev_panel_width=629, dev_panel_height=800)
        s.validate()
        assert s.dev_panel_width == 629
        assert s.dev_panel_height == 800
