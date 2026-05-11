"""Embeddable AI Writing Profiles UI.

Profile selection is the *single* source of truth for whether rewriting is
enabled.  Picking ``"None"`` disables ``settings.professional_mode``; picking
any actual profile enables it (after the one-time disclosure).

API key, provider and default model live in :class:`AIProvidersWidget` —
strictly separate from per-profile rewrite behaviour.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Optional, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import DEFAULT_PRESETS_DIR, Settings
from .pro_preset import (
    BUILTIN_PRESET_NAMES,
    ProPreset,
    delete_preset,
    load_all_presets,
    save_preset,
)

log = logging.getLogger(__name__)

PROFILE_NONE = "None"


class ProModeWidget(QWidget):
    """AI writing profile editor — auto-applied; no Apply button.

    Profile selection alone toggles ``settings.professional_mode``.  Rewrite
    options, protected terms, and advanced instructions are committed back
    to the active preset on every change.
    """

    settings_applied = Signal()
    presets_changed = Signal()

    def __init__(
        self,
        settings: Settings,
        on_disclosure_required: Optional[Callable[[], bool]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._on_disclosure_required = on_disclosure_required
        self._presets: dict[str, ProPreset] = {}
        self._displayed_preset_name: str = ""
        self._presets_dir = DEFAULT_PRESETS_DIR
        self._load_presets()
        self._build_ui()
        self._populate()

    def _load_presets(self) -> None:
        self._presets = load_all_presets(self._presets_dir)

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self) -> None:
        from .theme import Color, Spacing, make_section
        from .main_window import ToggleSwitch

        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        outer.setSpacing(Spacing.MD)

        profile_section, profile_form = make_section("AI Writing Profiles", self)
        profile_section.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )

        # ── Profile dropdown + CRUD buttons ──────────────────────────────
        profile_row = QHBoxLayout()
        profile_row.setSpacing(Spacing.SM)
        profile_row.addWidget(QLabel("Profile"))
        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(220)
        self._preset_combo.currentTextChanged.connect(self._on_preset_selected)
        profile_row.addWidget(self._preset_combo, 1)

        self._btn_new_preset = QPushButton("New")
        self._btn_new_preset.clicked.connect(self._on_new_preset)
        profile_row.addWidget(self._btn_new_preset)

        self._btn_dup_preset = QPushButton("Duplicate")
        self._btn_dup_preset.clicked.connect(self._on_duplicate_preset)
        profile_row.addWidget(self._btn_dup_preset)

        self._btn_del_preset = QPushButton("Delete")
        self._btn_del_preset.clicked.connect(self._on_delete_preset)
        profile_row.addWidget(self._btn_del_preset)
        profile_form.addRow(profile_row)

        # ── Rewrite options ──────────────────────────────────────────────
        rewrite_row = QHBoxLayout()
        rewrite_row.setSpacing(Spacing.MD)
        rewrite_label = QLabel("Rewrite Options")
        rewrite_label.setStyleSheet(f"color: {Color.TEXT_HEADING}; font-weight: 600;")
        rewrite_row.addWidget(rewrite_label)

        self._preset_fix_tone = ToggleSwitch("Tone")
        self._preset_fix_tone.setToolTip("Adjusts wording to match the selected profile")
        self._preset_fix_tone.toggled.connect(self._on_field_changed)
        rewrite_row.addWidget(self._preset_fix_tone)

        self._preset_fix_grammar = ToggleSwitch("Grammar")
        self._preset_fix_grammar.setToolTip("Corrects grammar and sentence structure")
        self._preset_fix_grammar.toggled.connect(self._on_field_changed)
        rewrite_row.addWidget(self._preset_fix_grammar)

        self._preset_fix_punctuation = ToggleSwitch("Punctuation")
        self._preset_fix_punctuation.setToolTip("Fixes punctuation and capitalization")
        self._preset_fix_punctuation.toggled.connect(self._on_field_changed)
        rewrite_row.addWidget(self._preset_fix_punctuation)
        rewrite_row.addStretch()
        profile_form.addRow(rewrite_row)

        # ── Protected Terms ──────────────────────────────────────────────
        self._protected_terms_group = QWidget(self)
        protected_layout = QVBoxLayout(self._protected_terms_group)
        protected_layout.setContentsMargins(0, 0, 0, 0)
        protected_layout.setSpacing(Spacing.SM)

        self._protected_label = QLabel("Protected Terms")
        self._protected_label.setStyleSheet(
            f"color: {Color.TEXT_HEADING}; font-weight: 600;"
        )
        protected_layout.addWidget(self._protected_label)

        self._protected_help = QLabel(
            "Terms Speakeasy should preserve exactly during rewriting."
        )
        self._protected_help.setStyleSheet(f"color: {Color.TEXT_MUTED};")
        protected_layout.addWidget(self._protected_help)

        self._vocab_edit = QPlainTextEdit()
        self._vocab_edit.setPlaceholderText("Kubernetes, gRPC, OAuth2, CI/CD")
        # ~3 visible rows; vertical resize allowed via parent scroll area.
        self._vocab_edit.setFixedHeight(64)
        self._vocab_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._vocab_edit.textChanged.connect(self._on_field_changed)
        protected_layout.addWidget(self._vocab_edit)
        profile_form.addRow(self._protected_terms_group)

        # ── Advanced Rewrite Instructions (collapsed by default) ─────────
        self._advanced_toggle = QPushButton("Advanced Rewrite Instructions  \u25b8")
        self._advanced_toggle.setCheckable(True)
        self._advanced_toggle.setToolTip("Optional. Detailed system prompt for this profile.")
        self._advanced_toggle.toggled.connect(self._on_advanced_toggled)
        profile_form.addRow(self._advanced_toggle)

        self._advanced_content = QWidget(self)
        adv_layout = QVBoxLayout(self._advanced_content)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(Spacing.SM)
        adv_help = QLabel(
            "Optional. Defines how this profile rewrites dictated text."
        )
        adv_help.setStyleSheet(f"color: {Color.TEXT_MUTED};")
        adv_layout.addWidget(adv_help)
        self._instructions_edit = QPlainTextEdit()
        self._instructions_edit.setPlaceholderText(
            "Define how this profile rewrites dictated text."
        )
        self._instructions_edit.setMinimumHeight(88)
        self._instructions_edit.setMaximumHeight(140)
        self._instructions_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._instructions_edit.textChanged.connect(self._on_field_changed)
        adv_layout.addWidget(self._instructions_edit)
        self._advanced_content.setVisible(False)
        profile_form.addRow(self._advanced_content)

        outer.addWidget(profile_section, 0, Qt.AlignmentFlag.AlignTop)
        outer.addStretch()

    # ── Populate ─────────────────────────────────────────────────────────

    def _populate(self) -> None:
        self._refresh_preset_combo()
        selected = (
            self.settings.pro_active_preset
            if self.settings.professional_mode
            else PROFILE_NONE
        )
        idx = self._preset_combo.findText(selected)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)

    def sync_from_settings(self) -> None:
        """Refresh externally controlled fields from the shared Settings object."""
        selected = (
            self.settings.pro_active_preset
            if self.settings.professional_mode
            else PROFILE_NONE
        )
        idx = self._preset_combo.findText(selected)
        if idx >= 0 and idx != self._preset_combo.currentIndex():
            self._preset_combo.blockSignals(True)
            self._preset_combo.setCurrentIndex(idx)
            self._preset_combo.blockSignals(False)
            self._on_preset_selected(self._preset_combo.currentText())

    def _refresh_preset_combo(self, select_name: str | None = None) -> None:
        current = select_name or self._preset_combo.currentText()
        if not current:
            current = (
                self.settings.pro_active_preset
                if self.settings.professional_mode
                else PROFILE_NONE
            )
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        self._preset_combo.addItem(PROFILE_NONE)
        for name in sorted(self._presets.keys()):
            self._preset_combo.addItem(name)
        idx = self._preset_combo.findText(current)
        self._preset_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._preset_combo.blockSignals(False)
        self._on_preset_selected(self._preset_combo.currentText())

    # ── Collapsible advanced section ─────────────────────────────────────

    def _on_advanced_toggled(self, checked: bool) -> None:
        self._advanced_toggle.setText(
            "Advanced Rewrite Instructions  \u25be" if checked
            else "Advanced Rewrite Instructions  \u25b8"
        )
        self._advanced_content.setVisible(checked)

    # ── Preset edit auto-apply ───────────────────────────────────────────

    def _on_field_changed(self, *_) -> None:
        preset = self._current_preset()
        if preset is None:
            return
        preset.fix_tone = self._preset_fix_tone.isChecked()
        preset.fix_grammar = self._preset_fix_grammar.isChecked()
        preset.fix_punctuation = self._preset_fix_punctuation.isChecked()
        preset.system_prompt = self._instructions_edit.toPlainText()
        preset.vocabulary = self._vocab_edit.toPlainText()
        save_preset(preset, self._presets_dir)
        self.settings_applied.emit()

    # ── Preset management ────────────────────────────────────────────────

    def _current_preset(self) -> ProPreset | None:
        name = self._preset_combo.currentText()
        return self._presets.get(name) if name and name != PROFILE_NONE else None

    def _flush_preset_edits_for(self, name: str) -> None:
        preset = self._presets.get(name)
        if preset is None:
            return
        preset.fix_tone = self._preset_fix_tone.isChecked()
        preset.fix_grammar = self._preset_fix_grammar.isChecked()
        preset.fix_punctuation = self._preset_fix_punctuation.isChecked()
        preset.system_prompt = self._instructions_edit.toPlainText()
        preset.vocabulary = self._vocab_edit.toPlainText()
        save_preset(preset, self._presets_dir)

    def _on_preset_selected(self, text: str) -> None:
        # Persist edits to the previously displayed preset before swapping.
        if (
            self._displayed_preset_name
            and self._displayed_preset_name in self._presets
            and self._displayed_preset_name != text
        ):
            self._flush_preset_edits_for(self._displayed_preset_name)

        if not text:
            return

        if text == PROFILE_NONE:
            self._displayed_preset_name = ""
            self.settings.professional_mode = False
            self._set_profile_editor_enabled(False)
            self.settings.save()
            self.presets_changed.emit()
            self.settings_applied.emit()
            return

        if not self.settings.pro_disclosure_accepted:
            if self._on_disclosure_required and not self._on_disclosure_required():
                self._preset_combo.blockSignals(True)
                self._preset_combo.setCurrentText(PROFILE_NONE)
                self._preset_combo.blockSignals(False)
                self._on_preset_selected(PROFILE_NONE)
                return

        preset = self._presets.get(text)
        if preset is None:
            return

        self._displayed_preset_name = text
        is_builtin = preset.name in BUILTIN_PRESET_NAMES

        for w in (self._preset_fix_tone, self._preset_fix_grammar,
                  self._preset_fix_punctuation, self._vocab_edit, self._instructions_edit):
            w.blockSignals(True)
        self._preset_fix_tone.setChecked(preset.fix_tone)
        self._preset_fix_grammar.setChecked(preset.fix_grammar)
        self._preset_fix_punctuation.setChecked(preset.fix_punctuation)
        self._instructions_edit.setPlainText(preset.system_prompt)
        self._vocab_edit.setPlainText(preset.vocabulary)
        for w in (self._preset_fix_tone, self._preset_fix_grammar,
                  self._preset_fix_punctuation, self._vocab_edit, self._instructions_edit):
            w.blockSignals(False)

        self._btn_del_preset.setEnabled(not is_builtin)
        self._set_profile_editor_enabled(True)
        self.settings.pro_active_preset = preset.name
        self.settings.professional_mode = True
        self.settings.save()
        self.presets_changed.emit()
        self.settings_applied.emit()

    def _set_profile_editor_enabled(self, enabled: bool) -> None:
        self._btn_dup_preset.setEnabled(enabled)
        if not enabled:
            self._btn_del_preset.setEnabled(False)
        for w in (self._preset_fix_tone, self._preset_fix_grammar,
                  self._preset_fix_punctuation, self._vocab_edit,
                  self._advanced_toggle, self._advanced_content):
            w.setEnabled(enabled)

    def _on_new_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self._presets or name == PROFILE_NONE:
            QMessageBox.warning(self, "Duplicate Name",
                                f"A profile named '{name}' already exists.")
            return
        preset = ProPreset(name=name)
        self._presets[name] = preset
        save_preset(preset, self._presets_dir)
        self._refresh_preset_combo(select_name=name)
        self.presets_changed.emit()

    def _on_duplicate_preset(self) -> None:
        source = self._current_preset()
        if source is None:
            return
        name, ok = QInputDialog.getText(
            self, "Duplicate Profile", "Name for the copy:",
            text=f"{source.name} (copy)",
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self._presets or name == PROFILE_NONE:
            QMessageBox.warning(self, "Duplicate Name",
                                f"A profile named '{name}' already exists.")
            return
        dup = ProPreset(**asdict(source))
        dup.name = name
        self._presets[name] = dup
        save_preset(dup, self._presets_dir)
        self._refresh_preset_combo(select_name=name)
        self.presets_changed.emit()

    def _on_delete_preset(self) -> None:
        preset = self._current_preset()
        if preset is None:
            return
        if preset.name in BUILTIN_PRESET_NAMES:
            QMessageBox.information(self, "Cannot Delete",
                                    "Built-in profiles cannot be deleted.")
            return
        reply = QMessageBox.question(
            self, "Delete Profile", f"Delete profile '{preset.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        delete_preset(preset.name, self._presets_dir)
        del self._presets[preset.name]
        self._displayed_preset_name = ""
        self.settings.professional_mode = False
        self.settings.save()
        self._refresh_preset_combo(select_name=PROFILE_NONE)
        self.presets_changed.emit()

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def presets(self) -> dict[str, ProPreset]:
        return self._presets
