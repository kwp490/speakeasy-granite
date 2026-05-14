"""AI Providers settings widget — provider, API key, validation, default model.

Lives in its own Developer Panel tab so infrastructure / credential settings
are clearly separated from the per-profile rewriting behaviour configured in
the AI Writing Profiles tab.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtGui import QGuiApplication, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import Settings
from .pro_preset import PRO_MODE_MODEL_OPTIONS
from .text_processor import (
    TextProcessor,
    delete_api_key_from_keyring,
    load_api_key_from_keyring,
    save_api_key_to_keyring,
)

log = logging.getLogger(__name__)

PROVIDER_OPENAI = "OpenAI"
PROVIDER_LOCAL_GRANITE = "Local Granite (built-in)"


class AIProvidersWidget(QWidget):
    """Provider, API key, validation, default cloud model — auto-applied."""

    settings_applied = Signal()
    api_key_changed = Signal(str)

    def __init__(
        self,
        settings: Settings,
        parent: Optional[QWidget] = None,
        api_key: str = "",
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._api_key = api_key
        self._build_ui()
        self._populate()

    # ── UI ───────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        from .theme import Color, Spacing, make_section, make_toggle_row
        from .main_window import ToggleSwitch

        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        outer.setSpacing(Spacing.MD)

        section, form = make_section("AI Providers", self)

        # Provider
        self._provider = QComboBox()
        self._provider.addItem(PROVIDER_OPENAI, "openai")
        self._provider.addItem(PROVIDER_LOCAL_GRANITE, "local_granite")
        self._provider.setToolTip(
            "Cloud provider used by AI Writing Profiles to rewrite dictation."
        )
        # Keep the future local provider visible, but disabled until the
        # rewrite pipeline can call Granite locally.
        model = self._provider.model()
        if isinstance(model, QStandardItemModel):
            local_item = model.item(1)
            if local_item is not None:
                local_item.setEnabled(False)
        form.addRow("Provider:", self._provider)

        # API key + reveal + paste
        key_row = QHBoxLayout()
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("sk-\u2026")
        self._api_key_edit.setToolTip("OpenAI API key (sk-...)")
        key_row.addWidget(self._api_key_edit)

        self._btn_reveal = QPushButton("\U0001f441")
        self._btn_reveal.setFixedWidth(32)
        self._btn_reveal.setCheckable(True)
        self._btn_reveal.setToolTip("Show / hide API key")
        self._btn_reveal.toggled.connect(self._toggle_visibility)
        key_row.addWidget(self._btn_reveal)

        self._btn_paste = QPushButton("Paste")
        self._btn_paste.setFixedWidth(56)
        self._btn_paste.setToolTip("Paste API key from clipboard")
        self._btn_paste.clicked.connect(self._on_paste)
        key_row.addWidget(self._btn_paste)
        form.addRow("API key:", key_row)

        # Validation row
        validate_row = QHBoxLayout()
        self._btn_validate = QPushButton("Validate API Key")
        self._btn_validate.clicked.connect(self._on_validate)
        validate_row.addWidget(self._btn_validate)
        self._lbl_status = QLabel("")
        validate_row.addWidget(self._lbl_status, 1)
        form.addRow(validate_row)

        # Remember credentials
        self._chk_remember = ToggleSwitch("")
        self._chk_remember.setToolTip(
            "Persist the API key in Windows Credential Manager so it survives restarts."
        )
        form.addRow(make_toggle_row(
            "Store credentials securely using Windows Credential Manager",
            self._chk_remember,
        ))

        # Default cloud model
        self._default_model = QComboBox()
        self._default_model.addItems(list(PRO_MODE_MODEL_OPTIONS))
        self._default_model.setToolTip("Default OpenAI chat model for AI Writing Profiles.")
        form.addRow("Default cloud model:", self._default_model)

        outer.addWidget(section)
        outer.addStretch()

        # Wire auto-apply
        self._api_key_edit.editingFinished.connect(self._on_api_key_committed)
        self._chk_remember.toggled.connect(self._on_remember_toggled)
        self._default_model.currentTextChanged.connect(self._on_model_changed)

    # ── Populate ─────────────────────────────────────────────────────────

    def _populate(self) -> None:
        # Provider
        idx = self._provider.findData(getattr(self.settings, "provider", "openai"))
        if idx >= 0:
            self._provider.setCurrentIndex(idx)

        # API key
        if not self._api_key and self.settings.store_api_key:
            stored = load_api_key_from_keyring()
            if stored:
                self._api_key = stored
        if self._api_key:
            self._api_key_edit.setText(self._api_key)

        self._chk_remember.setChecked(self.settings.store_api_key)

        midx = self._default_model.findText(self.settings.pro_default_model)
        if midx >= 0:
            self._default_model.setCurrentIndex(midx)

    def sync_from_settings(self) -> None:
        """Refresh from external mutations (e.g. settings.json reload)."""
        self._chk_remember.blockSignals(True)
        self._chk_remember.setChecked(self.settings.store_api_key)
        self._chk_remember.blockSignals(False)

        midx = self._default_model.findText(self.settings.pro_default_model)
        if midx >= 0:
            self._default_model.blockSignals(True)
            self._default_model.setCurrentIndex(midx)
            self._default_model.blockSignals(False)

    # ── Actions ──────────────────────────────────────────────────────────

    def _toggle_visibility(self, show: bool) -> None:
        self._api_key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        )

    def _on_paste(self) -> None:
        cb = QGuiApplication.clipboard()
        if cb is None:
            return
        text = (cb.text() or "").strip()
        if not text:
            return
        self._api_key_edit.setText(text)
        self._on_api_key_committed()

    def _on_api_key_committed(self) -> None:
        new_key = self._api_key_edit.text().strip()
        if new_key == self._api_key:
            return
        self._api_key = new_key
        if self.settings.store_api_key:
            if new_key:
                save_api_key_to_keyring(new_key)
            else:
                delete_api_key_from_keyring()
        self._lbl_status.setText("")
        self.api_key_changed.emit(self._api_key)
        self.settings_applied.emit()

    def _on_remember_toggled(self, checked: bool) -> None:
        self.settings.store_api_key = checked
        if checked and self._api_key:
            save_api_key_to_keyring(self._api_key)
        elif not checked:
            delete_api_key_from_keyring()
        self.settings.save()
        self.settings_applied.emit()

    def _on_model_changed(self, model: str) -> None:
        if not model or model == self.settings.pro_default_model:
            return
        self.settings.pro_default_model = model
        self.settings.save()
        self.settings_applied.emit()

    def _on_validate(self) -> None:
        from .theme import Color
        from .workers import Worker

        key = self._api_key_edit.text().strip()
        if not key:
            self._lbl_status.setText("\u274c No API key entered")
            self._lbl_status.setStyleSheet(f"color: {Color.DANGER};")
            return

        self._lbl_status.setText("Validating\u2026")
        self._lbl_status.setStyleSheet(f"color: {Color.TEXT_MUTED};")
        self._btn_validate.setEnabled(False)

        model = self._default_model.currentText()

        def _do_validate():
            return TextProcessor(api_key=key, model=model).validate_key()

        worker = Worker(_do_validate)
        worker.signals.result.connect(self._on_validate_result)
        worker.signals.error.connect(self._on_validate_error)
        QThreadPool.globalInstance().start(worker)

    def _on_validate_result(self, result: tuple) -> None:
        from .theme import Color
        self._btn_validate.setEnabled(True)
        ok, msg = result
        if ok:
            self._lbl_status.setText(f"\u2705 {msg}")
            self._lbl_status.setStyleSheet(f"color: {Color.SUCCESS};")
        else:
            self._lbl_status.setText(f"\u274c {msg}")
            self._lbl_status.setStyleSheet(f"color: {Color.DANGER};")

    def _on_validate_error(self, err: str) -> None:
        from .theme import Color
        self._btn_validate.setEnabled(True)
        self._lbl_status.setText(f"\u274c {err}")
        self._lbl_status.setStyleSheet(f"color: {Color.DANGER};")

    def focus_api_key(self) -> None:
        self._api_key_edit.setFocus()
        self._api_key_edit.selectAll()

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def api_key(self) -> str:
        return self._api_key
