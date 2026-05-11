"""Tests for the ProModeWidget (AI Writing Profiles editor) — v2 UI overhaul.

Profile selection is the *single* source of truth for whether rewriting is
enabled.  The API/model fields have moved to :mod:`speakeasy.ai_providers_widget`.
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
        from PySide6.QtWidgets import QApplication  # noqa: F401
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

    def test_settings_applied_signal_defined(self):
        assert "settings_applied" in self._source

    def test_presets_changed_signal_defined(self):
        assert "presets_changed" in self._source

    def test_no_enable_toggle(self):
        # Profile selection alone controls enable state
        assert "_chk_enable" not in self._source
        assert "Enable Professional Mode" not in self._source
        assert "Enable AI Writing Profiles" not in self._source

    def test_no_apply_button(self):
        # Auto-apply only — no separate Apply button on this tab
        assert "_btn_apply" not in self._source
        assert "_on_apply" not in self._method_names()

    def test_no_api_section(self):
        # API key/model/validation moved to AI Providers tab
        assert "_pro_api_key" not in self._source
        assert "_btn_eye" not in self._source
        assert "_btn_validate_key" not in self._source
        assert "_pro_model" not in self._source
        assert "Developer API Settings" not in self._source

    def test_has_sync_from_settings(self):
        assert "sync_from_settings" in self._method_names()

    def test_has_preset_crud_methods(self):
        names = self._method_names()
        assert "_on_new_preset" in names
        assert "_on_duplicate_preset" in names
        assert "_on_delete_preset" in names

    def test_has_advanced_collapsible(self):
        assert "_advanced_toggle" in self._source
        assert "_advanced_content" in self._source

    def test_protected_terms_label_present(self):
        assert "Protected Terms" in self._source

    def test_protected_terms_uses_compact_group(self):
        assert "_protected_terms_group" in self._source
        assert "_protected_help" in self._source

    def test_profile_none_constant(self):
        assert "PROFILE_NONE" in self._source


# ═══════════════════════════════════════════════════════════════════════════════
# Live widget tests
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not _qt_available(), reason="PySide6 not available")
class TestProModeWidgetLive:
    """Integration tests for ProModeWidget."""

    @pytest.fixture
    def pro_widget(self, tmp_path, monkeypatch):
        from speakeasy.config import Settings
        from speakeasy.pro_mode_widget import ProModeWidget
        import speakeasy.pro_preset as pp

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        presets_dir = config_dir / "presets"
        presets_dir.mkdir()
        # Seed built-in presets so the combo has > 1 entry
        pp.bootstrap_presets(presets_dir)
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_DIR", config_dir)
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_FILE", config_dir / "settings.json")
        monkeypatch.setattr("speakeasy.config.DEFAULT_PRESETS_DIR", presets_dir)
        monkeypatch.setattr("speakeasy.pro_mode_widget.DEFAULT_PRESETS_DIR", presets_dir)

        settings = Settings(pro_disclosure_accepted=True)
        widget = ProModeWidget(settings=settings, on_disclosure_required=None)
        return widget, settings

    def test_widget_constructs_without_disclosure_callback(self, pro_widget):
        widget, _ = pro_widget
        assert widget is not None

    def test_widget_constructs_with_disclosure_callback(self, tmp_path, monkeypatch):
        from speakeasy.config import Settings
        from speakeasy.pro_mode_widget import ProModeWidget
        import speakeasy.pro_preset as pp

        config_dir = tmp_path / "cfg"
        config_dir.mkdir()
        presets_dir = config_dir / "presets"
        presets_dir.mkdir()
        pp.bootstrap_presets(presets_dir)
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_DIR", config_dir)
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_FILE", config_dir / "settings.json")
        monkeypatch.setattr("speakeasy.config.DEFAULT_PRESETS_DIR", presets_dir)
        monkeypatch.setattr("speakeasy.pro_mode_widget.DEFAULT_PRESETS_DIR", presets_dir)

        spy = MagicMock(return_value=True)
        widget = ProModeWidget(settings=Settings(), on_disclosure_required=spy)
        assert widget is not None

    def test_preset_combo_first_item_is_none(self, pro_widget):
        widget, _ = pro_widget
        assert widget._preset_combo.count() > 1
        assert widget._preset_combo.itemText(0) == "None"

    def test_selecting_profile_enables_pro_mode(self, pro_widget):
        widget, settings = pro_widget
        # find first non-None entry
        widget._preset_combo.setCurrentIndex(1)
        assert settings.professional_mode is True
        assert settings.pro_active_preset == widget._preset_combo.currentText()

    def test_selecting_none_disables_pro_mode(self, pro_widget):
        widget, settings = pro_widget
        widget._preset_combo.setCurrentIndex(1)
        assert settings.professional_mode is True
        widget._preset_combo.setCurrentText("None")
        assert settings.professional_mode is False

    def test_disclosure_invoked_when_not_accepted(self, tmp_path, monkeypatch):
        from speakeasy.config import Settings
        from speakeasy.pro_mode_widget import ProModeWidget
        import speakeasy.pro_preset as pp

        config_dir = tmp_path / "cfg2"
        config_dir.mkdir()
        presets_dir = config_dir / "presets"
        presets_dir.mkdir()
        pp.bootstrap_presets(presets_dir)
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_DIR", config_dir)
        monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_FILE", config_dir / "settings.json")
        monkeypatch.setattr("speakeasy.config.DEFAULT_PRESETS_DIR", presets_dir)
        monkeypatch.setattr("speakeasy.pro_mode_widget.DEFAULT_PRESETS_DIR", presets_dir)

        spy = MagicMock(return_value=False)  # decline
        settings = Settings(pro_disclosure_accepted=False)
        widget = ProModeWidget(settings=settings, on_disclosure_required=spy)

        widget._preset_combo.setCurrentIndex(1)
        spy.assert_called_once()
        assert settings.professional_mode is False
        assert widget._preset_combo.currentText() == "None"

    def test_disclosure_not_invoked_when_already_accepted(self, pro_widget):
        widget, settings = pro_widget
        # pro_widget fixture already sets pro_disclosure_accepted=True
        widget._preset_combo.setCurrentIndex(1)
        assert settings.professional_mode is True

    def test_advanced_collapsed_by_default(self, pro_widget):
        widget, _ = pro_widget
        assert not widget._advanced_content.isVisible() or not widget._advanced_toggle.isChecked()
        assert widget._advanced_toggle.isCheckable()

    def test_protected_terms_compact_height(self, pro_widget):
        widget, _ = pro_widget
        # Approximately 3 visible rows
        assert widget._vocab_edit.maximumHeight() <= 100

    def test_protected_terms_label_help_and_editor_are_grouped(self, pro_widget):
        widget, _ = pro_widget
        layout = widget._protected_terms_group.layout()
        assert widget._protected_label.parent() is widget._protected_terms_group
        assert widget._protected_help.parent() is widget._protected_terms_group
        assert widget._vocab_edit.parent() is widget._protected_terms_group
        assert layout.indexOf(widget._protected_label) < layout.indexOf(widget._protected_help)
        assert layout.indexOf(widget._protected_help) < layout.indexOf(widget._vocab_edit)
        assert layout.spacing() <= 10

    def test_loaded_rewrite_switches_match_visual_state(self, pro_widget):
        widget, _ = pro_widget
        widget._preset_combo.setCurrentText("General Professional")
        preset = widget.presets["General Professional"]

        assert widget._preset_fix_tone.isChecked() is preset.fix_tone
        assert widget._preset_fix_grammar.isChecked() is preset.fix_grammar
        assert widget._preset_fix_punctuation.isChecked() is preset.fix_punctuation
        assert widget._preset_fix_tone._knob_pos == pytest.approx(1.0)
        assert widget._preset_fix_grammar._knob_pos == pytest.approx(1.0)
        assert widget._preset_fix_punctuation._knob_pos == pytest.approx(1.0)

    def test_toggle_switch_syncs_when_signals_are_blocked(self):
        from speakeasy.main_window import ToggleSwitch

        switch = ToggleSwitch("Tone")
        switch.blockSignals(True)
        switch.setChecked(True)
        switch.blockSignals(False)

        assert switch.isChecked() is True
        assert switch._knob_pos == pytest.approx(1.0)

    def test_sync_from_settings_refreshes_none(self, pro_widget):
        widget, settings = pro_widget
        settings.professional_mode = False
        widget.sync_from_settings()
        assert widget._preset_combo.currentText() == "None"

    def test_sync_from_settings_refreshes_active_preset(self, pro_widget):
        widget, settings = pro_widget
        target = widget._preset_combo.itemText(1)
        settings.pro_active_preset = target
        settings.professional_mode = True
        widget.sync_from_settings()
        assert widget._preset_combo.currentText() == target

    def test_presets_property(self, pro_widget):
        widget, _ = pro_widget
        assert isinstance(widget.presets, dict)
        assert len(widget.presets) > 0

    def test_no_api_key_attribute(self, pro_widget):
        widget, _ = pro_widget
        assert not hasattr(widget, "_pro_api_key")
        assert not hasattr(widget, "api_key")

    def test_rewrite_options_present(self, pro_widget):
        widget, _ = pro_widget
        assert widget._preset_fix_tone is not None
        assert widget._preset_fix_grammar is not None
        assert widget._preset_fix_punctuation is not None
        assert widget._preset_fix_tone.text() == "Tone"
        assert widget._preset_fix_grammar.text() == "Grammar"
        assert widget._preset_fix_punctuation.text() == "Punctuation"
