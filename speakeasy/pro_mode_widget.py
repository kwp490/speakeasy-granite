"""Embeddable Professional Mode UI — replaces the old modal ProSettingsDialog."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Optional, Callable

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
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
from .text_processor import (
    TextProcessor,
    delete_api_key_from_keyring,
    load_api_key_from_keyring,
    save_api_key_to_keyring,
)

log = logging.getLogger(__name__)


class ProModeWidget(QWidget):
    """Pro Mode preset editor + API key + custom instructions + vocabulary.

    Uses the same auto-apply-vs-Apply pattern as SettingsWidget:
      - Auto-apply: enable toggle, active preset selection, custom instructions, vocabulary
      - Risky (Apply required): API key, store_api_key toggle, preset CRUD operations
    """

    settings_applied = Signal()
    presets_changed = Signal()  # so MainWindow can refresh its preset combo

    def __init__(
        self,
        settings: Settings,
        on_disclosure_required: Optional[Callable[[], bool]] = None,
        parent: Optional[QWidget] = None,
        api_key: str = "",
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._on_disclosure_required = on_disclosure_required
        self._api_key = api_key
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
        from .theme import Color, Spacing, make_section, make_toggle_row
        from .main_window import ToggleSwitch

        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        outer.setSpacing(Spacing.SECTION)  # 20px between sections

        # ── Enable section ───────────────────────────────────────────────
        enable_section, enable_form = make_section("Enable", self)
        self._pro_enabled = ToggleSwitch("")
        self._pro_enabled.toggled.connect(self._on_enable_toggled)
        enable_form.addRow(make_toggle_row("Enable Professional Mode", self._pro_enabled))
        outer.addWidget(enable_section)

        # ── API section ──────────────────────────────────────────────────
        api_section, api_form = make_section("API", self)

        self._pro_model = QComboBox()
        self._pro_model.setEditable(True)
        self._pro_model.addItems(["gpt-5.4-mini", "gpt-5.4-nano"])
        api_form.addRow("Default model:", self._pro_model)

        key_row = QHBoxLayout()
        self._pro_api_key = QLineEdit()
        self._pro_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._pro_api_key.setPlaceholderText("sk-\u2026")
        key_row.addWidget(self._pro_api_key)

        self._btn_eye = QPushButton("\U0001f441")
        self._btn_eye.setFixedWidth(32)
        self._btn_eye.setCheckable(True)
        self._btn_eye.setToolTip("Show / hide API key")
        self._btn_eye.toggled.connect(self._toggle_key_visibility)
        key_row.addWidget(self._btn_eye)
        api_form.addRow("API key:", key_row)

        self._pro_store_key = ToggleSwitch("")
        api_form.addRow(make_toggle_row("Remember API key (Windows Credential Manager)", self._pro_store_key))

        validate_row = QHBoxLayout()
        self._btn_validate_key = QPushButton("Validate API Key")
        self._btn_validate_key.clicked.connect(self._on_validate_api_key)
        validate_row.addWidget(self._btn_validate_key)
        self._lbl_validate_result = QLabel("")
        validate_row.addWidget(self._lbl_validate_result)
        validate_row.addStretch()
        api_form.addRow(validate_row)

        outer.addWidget(api_section)

        # ── Presets section ──────────────────────────────────────────────
        presets_section, presets_form = make_section("Presets", self)

        preset_select_row = QHBoxLayout()
        preset_select_row.addWidget(QLabel("Preset:"))
        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(200)
        self._preset_combo.currentTextChanged.connect(self._on_preset_selected)
        preset_select_row.addWidget(self._preset_combo, 1)
        presets_form.addRow(preset_select_row)

        btn_row = QHBoxLayout()
        self._btn_new_preset = QPushButton("New")
        self._btn_new_preset.clicked.connect(self._on_new_preset)
        btn_row.addWidget(self._btn_new_preset)

        self._btn_dup_preset = QPushButton("Duplicate")
        self._btn_dup_preset.clicked.connect(self._on_duplicate_preset)
        btn_row.addWidget(self._btn_dup_preset)

        self._btn_del_preset = QPushButton("Delete")
        self._btn_del_preset.clicked.connect(self._on_delete_preset)
        btn_row.addWidget(self._btn_del_preset)

        btn_row.addStretch()
        presets_form.addRow(btn_row)

        self._preset_name_edit = QLineEdit()
        self._preset_name_edit.setPlaceholderText("Preset name")
        presets_form.addRow("Name:", self._preset_name_edit)

        self._preset_model = QComboBox()
        self._preset_model.setEditable(True)
        self._preset_model.addItems(["(use default)", "gpt-5.4-mini", "gpt-5.4-nano"])
        presets_form.addRow("Model override:", self._preset_model)

        self._preset_fix_tone = ToggleSwitch("Fix tone")
        presets_form.addRow(self._preset_fix_tone)

        self._preset_fix_grammar = ToggleSwitch("Fix grammar")
        presets_form.addRow(self._preset_fix_grammar)

        self._preset_fix_punctuation = ToggleSwitch(
            "Fix punctuation && capitalization"
        )
        presets_form.addRow(self._preset_fix_punctuation)

        outer.addWidget(presets_section)

        # ── Instructions section ─────────────────────────────────────────
        instructions_section, instructions_form = make_section("Instructions", self)

        self._lbl_instructions_preset = QLabel("Select a preset first.")
        instructions_form.addRow(self._lbl_instructions_preset)

        self._instructions_edit = QPlainTextEdit()
        self._instructions_edit.setPlaceholderText(
            "Enter custom system prompt instructions for the selected preset\u2026\n\n"
            "Example: Always use Oxford comma. Keep paragraphs under 3 sentences."
        )
        self._instructions_edit.setMinimumHeight(100)
        instructions_form.addRow(self._instructions_edit)

        outer.addWidget(instructions_section)

        # ── Vocabulary section ───────────────────────────────────────────
        vocab_section, vocab_form = make_section("Vocabulary", self)

        self._lbl_vocab_preset = QLabel("Select a preset first.")
        vocab_form.addRow(self._lbl_vocab_preset)

        self._vocab_edit = QPlainTextEdit()
        self._vocab_edit.setPlaceholderText(
            "Enter domain-specific terms to preserve (comma or newline separated)\u2026\n\n"
            "Example:\nKubernetes, gRPC, OAuth2, CI/CD"
        )
        self._vocab_edit.setMinimumHeight(100)
        vocab_form.addRow(self._vocab_edit)

        outer.addWidget(vocab_section)

        # ── Action row ───────────────────────────────────────────────────
        action_row = QHBoxLayout()
        self._btn_apply = QPushButton("Apply")
        self._btn_apply.setToolTip("Save API key and preset changes")
        self._btn_apply.clicked.connect(self._on_apply)
        action_row.addWidget(self._btn_apply)
        action_row.addStretch()
        outer.addLayout(action_row)

    # ── Populate ─────────────────────────────────────────────────────────

    def _populate(self) -> None:
        self._pro_enabled.setChecked(self.settings.professional_mode)

        if self._api_key:
            self._pro_api_key.setText(self._api_key)
        elif self.settings.store_api_key:
            stored = load_api_key_from_keyring()
            if stored:
                self._pro_api_key.setText(stored)
                self._api_key = stored

        self._pro_store_key.setChecked(self.settings.store_api_key)

        self._refresh_preset_combo()
        idx = self._preset_combo.findText(self.settings.pro_active_preset)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)

    def _refresh_preset_combo(self, select_name: str | None = None) -> None:
        current = select_name or self._preset_combo.currentText()
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        for name in sorted(self._presets.keys()):
            self._preset_combo.addItem(name)
        idx = self._preset_combo.findText(current)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)
        self._preset_combo.blockSignals(False)
        if self._preset_combo.currentText():
            self._on_preset_selected(self._preset_combo.currentText())

    # ── Auto-apply: enable toggle ────────────────────────────────────────

    def _on_enable_toggled(self, checked: bool) -> None:
        if checked and not self.settings.pro_disclosure_accepted:
            if self._on_disclosure_required and not self._on_disclosure_required():
                self._pro_enabled.blockSignals(True)
                self._pro_enabled.setChecked(False)
                self._pro_enabled.blockSignals(False)
                return
        self.settings.professional_mode = checked
        self.settings.save()
        self.settings_applied.emit()

    # ── Apply (risky) ────────────────────────────────────────────────────

    def _on_apply(self) -> None:
        self._flush_preset_edits()

        self._api_key = self._pro_api_key.text().strip()
        self.settings.store_api_key = self._pro_store_key.isChecked()

        if self.settings.store_api_key and self._api_key:
            save_api_key_to_keyring(self._api_key)
        elif not self.settings.store_api_key:
            delete_api_key_from_keyring()

        preset_name = self._preset_combo.currentText()
        if preset_name:
            self.settings.pro_active_preset = preset_name

        for name, preset in self._presets.items():
            save_preset(preset, self._presets_dir)

        if self.settings.professional_mode and not self._api_key:
            QMessageBox.warning(
                self,
                "No API Key",
                "Professional Mode is enabled but no API key has been entered.\n\n"
                "Text cleanup will not run until a valid OpenAI API key is configured.",
            )

        self.settings.save()
        self.settings_applied.emit()
        self.presets_changed.emit()
        log.info("Professional Mode settings applied")

    # ── Preset management ────────────────────────────────────────────────

    def _current_preset(self) -> ProPreset | None:
        name = self._preset_combo.currentText()
        return self._presets.get(name) if name else None

    def _flush_preset_edits(self) -> None:
        preset = self._current_preset()
        if preset is None:
            return

        old_name = preset.name
        new_name = self._preset_name_edit.text().strip()

        if new_name and new_name != old_name:
            if old_name not in BUILTIN_PRESET_NAMES:
                del self._presets[old_name]
                preset.name = new_name
                self._presets[new_name] = preset

        model_text = self._preset_model.currentText().strip()
        preset.model = "" if model_text == "(use default)" else model_text
        preset.fix_tone = self._preset_fix_tone.isChecked()
        preset.fix_grammar = self._preset_fix_grammar.isChecked()
        preset.fix_punctuation = self._preset_fix_punctuation.isChecked()
        preset.system_prompt = self._instructions_edit.toPlainText()
        preset.vocabulary = self._vocab_edit.toPlainText()

    def _on_preset_selected(self, text: str) -> None:
        if self._displayed_preset_name and self._displayed_preset_name in self._presets:
            self._flush_preset_edits_for(self._displayed_preset_name)

        if not text:
            return

        preset = self._presets.get(text)
        if preset is None:
            return

        self._displayed_preset_name = text

        self._preset_name_edit.setText(preset.name)
        is_builtin = preset.name in BUILTIN_PRESET_NAMES
        self._preset_name_edit.setReadOnly(is_builtin)

        model = preset.model or "(use default)"
        idx = self._preset_model.findText(model)
        if idx >= 0:
            self._preset_model.setCurrentIndex(idx)
        else:
            self._preset_model.setCurrentText(model)

        self._preset_fix_tone.setChecked(preset.fix_tone)
        self._preset_fix_grammar.setChecked(preset.fix_grammar)
        self._preset_fix_punctuation.setChecked(preset.fix_punctuation)

        self._instructions_edit.setPlainText(preset.system_prompt)
        self._lbl_instructions_preset.setText(f"Custom instructions for: {preset.name}")

        self._vocab_edit.setPlainText(preset.vocabulary)
        self._lbl_vocab_preset.setText(f"Vocabulary for: {preset.name}")

        self._btn_del_preset.setEnabled(not is_builtin)

    def _flush_preset_edits_for(self, name: str) -> None:
        preset = self._presets.get(name)
        if preset is None:
            return
        model_text = self._preset_model.currentText().strip()
        preset.model = "" if model_text == "(use default)" else model_text
        preset.fix_tone = self._preset_fix_tone.isChecked()
        preset.fix_grammar = self._preset_fix_grammar.isChecked()
        preset.fix_punctuation = self._preset_fix_punctuation.isChecked()
        preset.system_prompt = self._instructions_edit.toPlainText()
        preset.vocabulary = self._vocab_edit.toPlainText()

    def _on_new_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "New Preset", "Preset name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self._presets:
            QMessageBox.warning(self, "Duplicate Name",
                                f"A preset named '{name}' already exists.")
            return
        preset = ProPreset(name=name)
        self._presets[name] = preset
        self._refresh_preset_combo(select_name=name)

    def _on_duplicate_preset(self) -> None:
        source = self._current_preset()
        if source is None:
            return
        name, ok = QInputDialog.getText(
            self, "Duplicate Preset", "Name for the copy:",
            text=f"{source.name} (copy)",
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self._presets:
            QMessageBox.warning(self, "Duplicate Name",
                                f"A preset named '{name}' already exists.")
            return
        dup = ProPreset(**asdict(source))
        dup.name = name
        self._presets[name] = dup
        self._refresh_preset_combo(select_name=name)

    def _on_delete_preset(self) -> None:
        preset = self._current_preset()
        if preset is None:
            return
        if preset.name in BUILTIN_PRESET_NAMES:
            QMessageBox.information(self, "Cannot Delete",
                                    "Built-in presets cannot be deleted.")
            return
        reply = QMessageBox.question(
            self, "Delete Preset", f"Delete preset '{preset.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        delete_preset(preset.name, self._presets_dir)
        del self._presets[preset.name]
        self._displayed_preset_name = ""
        self._refresh_preset_combo()

    # ── API key helpers ──────────────────────────────────────────────────

    def _toggle_key_visibility(self, show: bool) -> None:
        self._pro_api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        )

    def _on_validate_api_key(self) -> None:
        from .theme import Color
        key = self._pro_api_key.text().strip()
        if not key:
            self._lbl_validate_result.setText("\u274c No API key entered")
            self._lbl_validate_result.setStyleSheet(f"color: {Color.DANGER};")
            return

        self._lbl_validate_result.setText("Validating\u2026")
        self._lbl_validate_result.setStyleSheet(f"color: {Color.TEXT_MUTED};")
        self._btn_validate_key.setEnabled(False)

        model = self._pro_model.currentText()

        def _do_validate():
            processor = TextProcessor(api_key=key, model=model)
            return processor.validate_key()

        from .workers import Worker
        worker = Worker(_do_validate)
        worker.signals.result.connect(self._on_validate_result)
        worker.signals.error.connect(self._on_validate_error)
        QThreadPool.globalInstance().start(worker)

    def _on_validate_result(self, result: tuple) -> None:
        from .theme import Color
        self._btn_validate_key.setEnabled(True)
        ok, msg = result
        if ok:
            self._lbl_validate_result.setText(f"\u2705 {msg}")
            self._lbl_validate_result.setStyleSheet(f"color: {Color.SUCCESS};")
        else:
            self._lbl_validate_result.setText(f"\u274c {msg}")
            self._lbl_validate_result.setStyleSheet(f"color: {Color.DANGER};")

    def _on_validate_error(self, err: str) -> None:
        from .theme import Color
        self._btn_validate_key.setEnabled(True)
        self._lbl_validate_result.setText(f"\u274c {err}")
        self._lbl_validate_result.setStyleSheet(f"color: {Color.DANGER};")

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def presets(self) -> dict[str, ProPreset]:
        return self._presets
