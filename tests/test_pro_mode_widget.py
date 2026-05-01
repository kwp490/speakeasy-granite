"""Tests for the ProModeWidget (replacement for the modal ProSettingsDialog).

Validates construction, enable toggle behaviour, and disclosure callback.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PRO_MODE_WIDGET_PATH = _REPO_ROOT / "speakeasy" / "pro_mode_widget.py"


def _qt_available() -> bool:
    try:
        from PySide6.QtWidgets import QApplication
        return True
    except ImportError:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# AST-level structural tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestProModeWidgetStructure:
    """AST checks on ProModeWidget class."""

    @classmethod
    def setup_class(cls):
        cls._source = _PRO_MODE_WIDGET_PATH.read_text(encoding="utf-8")
        cls._tree = ast.parse(cls._source, filename="pro_mode_widget.py")
        cls._pw_class = None
        for node in ast.walk(cls._tree):
            if isinstance(node, ast.ClassDef) and node.name == "ProModeWidget":
                cls._pw_class = node
                break
        assert cls._pw_class is not None

    def _method_names(self):
        return [n.name for n in ast.walk(self._pw_class) if isinstance(n, ast.FunctionDef)]

    def _method_source(self, name: str) -> str:
        for node in ast.walk(self._pw_class):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.get_source_segment(self._source, node) or ""
        pytest.fail(f"Method '{name}' not found in ProModeWidget")

    def test_settings_applied_signal_defined(self):
        assert "settings_applied" in self._source

    def test_presets_changed_signal_defined(self):
        assert "presets_changed" in self._source

    def test_has_on_enable_toggled(self):
        assert "_on_enable_toggled" in self._method_names()

    def test_has_on_apply(self):
        assert "_on_apply" in self._method_names()

    def test_has_preset_crud_methods(self):
        names = self._method_names()
        assert "_on_new_preset" in names
        assert "_on_duplicate_preset" in names
        assert "_on_delete_preset" in names

    def test_disclosure_callback_stored(self):
        src = self._method_source("__init__")
        assert "_on_disclosure_required" in src


# ═══════════════════════════════════════════════════════════════════════════════
# Live widget tests
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not _qt_available(), reason="PySide6 not available")
class TestProModeWidgetLive:
    """Integration tests for ProModeWidget with mocked keyring."""

    @pytest.fixture
    def pro_widget(self, tmp_path, monkeypatch):
        from speakeasy.config import Settings
        from speakeasy.pro_mode_widget import ProModeWidget

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        presets_dir = config_dir / "presets"
        presets_dir.mkdir()
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_DIR", config_dir)
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_FILE", config_dir / "settings.json")
        monkeypatch.setattr("speakeasy.config.DEFAULT_PRESETS_DIR", presets_dir)
        # Mock keyring to avoid OS credential store access
        monkeypatch.setattr("speakeasy.pro_mode_widget.load_api_key_from_keyring", lambda: "")
        monkeypatch.setattr("speakeasy.pro_mode_widget.save_api_key_to_keyring", lambda k: None)
        monkeypatch.setattr("speakeasy.pro_mode_widget.delete_api_key_from_keyring", lambda: None)

        settings = Settings()
        widget = ProModeWidget(settings=settings, on_disclosure_required=None)
        return widget, settings

    def test_pro_mode_widget_constructs_without_disclosure_callback(self, pro_widget):
        widget, _ = pro_widget
        assert widget is not None

    def test_pro_mode_widget_constructs_with_disclosure_callback(self, tmp_path, monkeypatch):
        from speakeasy.config import Settings
        from speakeasy.pro_mode_widget import ProModeWidget

        config_dir = tmp_path / "config2"
        config_dir.mkdir()
        presets_dir = config_dir / "presets"
        presets_dir.mkdir()
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_DIR", config_dir)
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_FILE", config_dir / "settings.json")
        monkeypatch.setattr("speakeasy.config.DEFAULT_PRESETS_DIR", presets_dir)
        monkeypatch.setattr("speakeasy.pro_mode_widget.load_api_key_from_keyring", lambda: "")

        spy = MagicMock(return_value=True)
        settings = Settings()
        widget = ProModeWidget(settings=settings, on_disclosure_required=spy)
        assert widget is not None

    def test_enabling_pro_mode_invokes_disclosure_when_not_accepted(self, tmp_path, monkeypatch):
        from speakeasy.config import Settings
        from speakeasy.pro_mode_widget import ProModeWidget

        config_dir = tmp_path / "config3"
        config_dir.mkdir()
        presets_dir = config_dir / "presets"
        presets_dir.mkdir()
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_DIR", config_dir)
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_FILE", config_dir / "settings.json")
        monkeypatch.setattr("speakeasy.config.DEFAULT_PRESETS_DIR", presets_dir)
        monkeypatch.setattr("speakeasy.pro_mode_widget.load_api_key_from_keyring", lambda: "")

        spy = MagicMock(return_value=False)  # decline disclosure
        settings = Settings(pro_disclosure_accepted=False)
        widget = ProModeWidget(settings=settings, on_disclosure_required=spy)

        widget._pro_enabled.setChecked(True)
        spy.assert_called_once()
        # Should NOT be enabled because disclosure was declined
        assert settings.professional_mode is False

    def test_disclosure_callback_not_invoked_when_already_accepted(self, tmp_path, monkeypatch):
        from speakeasy.config import Settings
        from speakeasy.pro_mode_widget import ProModeWidget

        config_dir = tmp_path / "config4"
        config_dir.mkdir()
        presets_dir = config_dir / "presets"
        presets_dir.mkdir()
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_DIR", config_dir)
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_FILE", config_dir / "settings.json")
        monkeypatch.setattr("speakeasy.config.DEFAULT_PRESETS_DIR", presets_dir)
        monkeypatch.setattr("speakeasy.pro_mode_widget.load_api_key_from_keyring", lambda: "")

        spy = MagicMock(return_value=True)
        settings = Settings(pro_disclosure_accepted=True)
        widget = ProModeWidget(settings=settings, on_disclosure_required=spy)

        widget._pro_enabled.setChecked(True)
        spy.assert_not_called()

    def test_enabling_pro_mode_saves_settings(self, pro_widget):
        """Toggling enable should auto-apply (save immediately)."""
        widget, settings = pro_widget
        settings.pro_disclosure_accepted = True
        widget._pro_enabled.setChecked(True)
        assert settings.professional_mode is True

    def test_disabling_pro_mode_saves_settings(self, pro_widget):
        widget, settings = pro_widget
        settings.pro_disclosure_accepted = True
        # First enable it
        widget._pro_enabled.setChecked(True)
        assert settings.professional_mode is True
        # Then disable it
        widget._pro_enabled.setChecked(False)
        assert settings.professional_mode is False

    def test_preset_combo_populated(self, pro_widget):
        widget, _ = pro_widget
        assert widget._preset_combo.count() > 0

    def test_selecting_preset_updates_detail_fields(self, pro_widget):
        widget, _ = pro_widget
        # Select a different preset
        if widget._preset_combo.count() > 1:
            widget._preset_combo.setCurrentIndex(1)
            name = widget._preset_combo.currentText()
            assert widget._preset_name_edit.text() == name

    def test_api_key_field_exists(self, pro_widget):
        widget, _ = pro_widget
        assert hasattr(widget, "_pro_api_key")

    def test_eye_button_toggles_visibility(self, pro_widget):
        widget, _ = pro_widget
        from PySide6.QtWidgets import QLineEdit
        assert widget._pro_api_key.echoMode() == QLineEdit.EchoMode.Password
        widget._btn_eye.setChecked(True)
        assert widget._pro_api_key.echoMode() == QLineEdit.EchoMode.Normal
        widget._btn_eye.setChecked(False)
        assert widget._pro_api_key.echoMode() == QLineEdit.EchoMode.Password

    def test_apply_emits_settings_applied(self, pro_widget, qtbot):
        widget, _ = pro_widget
        with qtbot.waitSignal(widget.settings_applied, timeout=1000):
            widget._on_apply()

    def test_apply_emits_presets_changed(self, pro_widget, qtbot):
        widget, _ = pro_widget
        with qtbot.waitSignal(widget.presets_changed, timeout=1000):
            widget._on_apply()

    def test_presets_property(self, pro_widget):
        widget, _ = pro_widget
        assert isinstance(widget.presets, dict)
        assert len(widget.presets) > 0

    def test_api_key_property(self, pro_widget):
        widget, _ = pro_widget
        assert isinstance(widget.api_key, str)

    def test_validate_api_key_no_key(self, pro_widget):
        widget, _ = pro_widget
        widget._pro_api_key.setText("")
        widget._on_validate_api_key()
        assert "No API key" in widget._lbl_validate_result.text()

    def test_flush_preset_edits_for_builtin(self, pro_widget):
        widget, _ = pro_widget
        # Ensure a preset is selected and flush works
        if widget._preset_combo.count() > 0:
            widget._preset_combo.setCurrentIndex(0)
            name = widget._preset_combo.currentText()
            widget._flush_preset_edits_for(name)
            # No crash expected

    def test_flush_preset_edits_for_nonexistent(self, pro_widget):
        widget, _ = pro_widget
        widget._flush_preset_edits_for("nonexistent_preset")
        # Should be a no-op, no crash
