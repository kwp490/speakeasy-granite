"""Tests for the Model Location UI in AdvancedSettingsWidget (Phase 3).

Covers §8.2: managed / custom-folder radios, removable/UNC badges, the
disabled remote placeholder, and that Apply writes the discriminated
``model_source`` schema.
"""

from __future__ import annotations

import pytest

from speakeasy.config import DEFAULT_MODELS_DIR, Settings


def _qt_available() -> bool:
    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _qt_available(), reason="PySide6 not available")


@pytest.fixture
def advanced_widget(tmp_path, monkeypatch):
    from speakeasy.settings_dialog import AdvancedSettingsWidget

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_DIR", config_dir)
    monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_FILE", config_dir / "settings.json")
    monkeypatch.setattr("speakeasy.config.DEFAULT_PRESETS_DIR", config_dir / "presets")
    (config_dir / "presets").mkdir()

    settings = Settings()
    settings.validate()
    widget = AdvancedSettingsWidget(settings)
    return widget, settings, config_dir


def test_default_selects_managed_and_disables_path(advanced_widget):
    widget, _, _ = advanced_widget
    assert widget._rb_managed.isChecked()
    assert not widget._model_path.isEnabled()
    assert widget._managed_path.text() == DEFAULT_MODELS_DIR


def test_remote_radio_enabled_and_toggles_fields(advanced_widget):
    widget, _, _ = advanced_widget
    assert widget._rb_remote.isEnabled() is True
    # Remote fields are disabled until the remote radio is selected.
    assert widget._remote_url.isEnabled() is False
    widget._rb_remote.setChecked(True)
    assert widget._remote_url.isEnabled() is True
    assert widget._remote_token.isEnabled() is True
    assert widget._btn_test_connection.isEnabled() is True


def test_apply_remote_writes_remote_source(advanced_widget):
    widget, settings, _ = advanced_widget
    settings.remote_disclosure_accepted = True  # skip the modal disclosure
    widget._rb_remote.setChecked(True)
    widget._remote_url.setText("http://10.0.0.42:8765")
    widget._on_apply()
    assert settings.model_source["type"] == "remote"
    assert settings.model_source["url"] == "http://10.0.0.42:8765"
    # Remote mirrors the managed default for the legacy path.
    assert settings.model_path == DEFAULT_MODELS_DIR


def test_apply_remote_invalid_url_aborts(advanced_widget):
    widget, settings, _ = advanced_widget
    settings.remote_disclosure_accepted = True
    widget._rb_remote.setChecked(True)
    widget._remote_url.setText("ftp://nope")
    widget._on_apply()
    # Invalid URL must not be committed.
    assert settings.model_source.get("type") != "remote" or not settings.model_source.get("url")
    assert "Invalid server URL" in widget._remote_status.text()


def test_typing_path_switches_to_custom(advanced_widget):
    widget, _, _ = advanced_widget
    widget._model_path.setText(r"D:\my-models")
    assert widget._rb_custom.isChecked()
    assert widget._btn_apply.isEnabled()


def test_apply_writes_local_dir_source(advanced_widget):
    widget, settings, _ = advanced_widget
    widget._rb_custom.setChecked(True)
    widget._model_path.setText(r"D:\my-models")
    widget._on_apply()
    assert settings.model_source == {"type": "local_dir", "path": r"D:\my-models"}
    assert settings.model_path == r"D:\my-models"


def test_apply_managed_writes_managed_source(advanced_widget):
    widget, settings, _ = advanced_widget
    # Switch to custom then back to managed and apply.
    widget._rb_custom.setChecked(True)
    widget._model_path.setText(r"D:\my-models")
    widget._rb_managed.setChecked(True)
    widget._on_apply()
    assert settings.model_source == {"type": "managed", "path": ""}
    assert settings.model_path == DEFAULT_MODELS_DIR


def test_unc_path_shows_network_badge(advanced_widget):
    widget, _, _ = advanced_widget
    widget._rb_custom.setChecked(True)
    widget._model_path.setText(r"\\nas01\share\models")
    assert "Network path" in widget._location_badge.text()


def test_managed_mode_clears_badge(advanced_widget):
    widget, _, _ = advanced_widget
    widget._rb_custom.setChecked(True)
    widget._model_path.setText(r"\\nas01\share\models")
    assert widget._location_badge.text()
    widget._rb_managed.setChecked(True)
    assert widget._location_badge.text() == ""


def test_restore_defaults_returns_to_managed(advanced_widget):
    widget, _, _ = advanced_widget
    widget._rb_custom.setChecked(True)
    widget._model_path.setText(r"D:\my-models")
    widget._on_restore_defaults()
    assert widget._rb_managed.isChecked()
    assert widget._model_path.text() == DEFAULT_MODELS_DIR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
