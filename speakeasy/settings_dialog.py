"""
Settings UI for SpeakEasy AI.

``SettingsWidget`` is the user-facing settings form used by the Developer Panel.
``AdvancedSettingsWidget`` contains developer/runtime tuning controls.
``SettingsDialog`` wraps it in a modal dialog for backward compatibility.

All settings fields are deferred until Apply. Device changes and model-path changes
emit reload requests from their respective tabs.
"""

from __future__ import annotations

import logging
from dataclasses import fields as dc_fields
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .audio import AudioRecorder
from ._build_variant import VARIANT
from .config import Settings

log = logging.getLogger(__name__)

# IBM Granite Speech 4.1 supported ASR languages
GRANITE_LANGUAGES = [
    ("auto", "Auto"),
    ("en", "English"),
    ("fr", "French"),
    ("de", "German"),
    ("es", "Spanish"),
    ("pt", "Portuguese"),
    ("ja", "Japanese"),
]

GRANITE_TRANSLATION_TARGETS = [
    "English",
    "French",
    "German",
    "Spanish",
    "Japanese",
    "Italian",
    "Mandarin",
]

GRANITE_FORMATTING_STYLES = [
    ("sentence_case", "Sentence case"),
    ("plain_text", "Plain text"),
    ("preserve_spoken_wording", "Preserve spoken wording"),
]


class SettingsWidget(QWidget):
    """Embeddable user-facing settings UI — all fields are deferred until Apply is clicked."""

    risky_change_pending = Signal()   # emitted when any field differs from saved state
    settings_applied = Signal()       # emitted after Apply succeeds
    reload_model_requested = Signal() # emitted if device changed on Apply

    def __init__(self, settings: Settings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(500)
        self.settings = settings
        self._snapshot = self._take_snapshot()
        self._build_ui()
        self._populate()
        self._wire_auto_apply()

    def _take_snapshot(self) -> dict:
        return {f.name: getattr(self.settings, f.name) for f in dc_fields(self.settings.__class__)
                if not f.name.startswith("_")}

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        from .theme import Color, Spacing, ghost_button_style, make_section, make_toggle_row
        from .main_window import ToggleSwitch

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.SECTION)  # 20px between sections

        # ── Model section ────────────────────────────────────────────────────
        model_section, engine_form = make_section("Model", self)

        self._device_combo = QComboBox()
        self._device_combo.addItems(["cuda", "cpu"])
        self._device_combo.setToolTip(
            "cuda (GPU): Uses your NVIDIA graphics card for transcription.\n"
            "Much faster — recommended if you have a GPU with ~5 GB of VRAM.\n\n"
            "cpu: Runs entirely on the processor — works on any machine,\n"
            "but transcription is significantly slower."
        )
        engine_form.addRow("Device:", self._device_combo)

        self._device_warning = QLabel(
            "\u26a0 CUDA is not available in the CPU edition."
            " Download and install the GPU version to use CUDA."
        )
        self._device_warning.setWordWrap(True)
        self._device_warning.setStyleSheet(f"color: {Color.DANGER}; font-weight: bold;")
        self._device_warning.setVisible(False)
        engine_form.addRow(self._device_warning)

        self._device_combo.currentTextChanged.connect(self._on_device_changed)

        self._language_combo = QComboBox()
        for code, label in GRANITE_LANGUAGES:
            display = label if code == "auto" else f"{label} ({code})"
            self._language_combo.addItem(display, code)
        self._language_combo.setToolTip(
            "The spoken language in your recordings.\n"
            "Choose Auto for Granite prompt-based language inference, or select\n"
            "the language you will be dictating in for best accuracy."
        )
        engine_form.addRow("Language:", self._language_combo)

        self._task_combo = QComboBox()
        self._task_combo.addItem("Transcribe", "transcribe")
        self._task_combo.addItem("Translate", "translate")
        self._task_combo.setToolTip(
            "Choose whether Granite should transcribe the speech as-is or\n"
            "translate it to the selected target language."
        )
        engine_form.addRow("Mode:", self._task_combo)

        self._translation_target = QComboBox()
        for target in GRANITE_TRANSLATION_TARGETS:
            self._translation_target.addItem(target, target)
        self._translation_target.setToolTip(
            "Target language for Granite speech translation."
        )
        engine_form.addRow("Translate to:", self._translation_target)
        self._translation_target_label = engine_form.labelForField(self._translation_target)

        self._keyword_bias = QLineEdit()
        self._keyword_bias.setPlaceholderText("Names, acronyms, jargon, product terms")
        self._keyword_bias.setToolTip(
            "Optional comma-separated keywords to bias Granite toward\n"
            "names, acronyms, and technical terms."
        )
        engine_form.addRow("Keywords:", self._keyword_bias)

        layout.addWidget(model_section)

        # ── Transcription Style section ──────────────────────────────────────
        style_section, style_form = make_section("Transcription Style", self)

        self._punctuation = ToggleSwitch("")
        self._punctuation.setToolTip(
            "Requests Granite prompt wording for punctuation and capitalization.\n"
            "When off, Granite receives the basic transcription prompt."
        )
        style_form.addRow(make_toggle_row("Punctuation and capitalization", self._punctuation))

        self._formatting_style = QComboBox()
        for value, label in GRANITE_FORMATTING_STYLES:
            self._formatting_style.addItem(label, value)
        self._formatting_style.setToolTip(
            "Controls the Granite prompt wording for ordinary dictation output."
        )
        style_form.addRow("Formatting style:", self._formatting_style)

        layout.addWidget(style_section)

        # ── Audio section ────────────────────────────────────────────────────
        audio_section, audio_form = make_section("Audio", self)

        self._mic_combo = QComboBox()
        self._mic_combo.addItem("System default", -1)
        try:
            for idx, name in AudioRecorder.list_input_devices():
                self._mic_combo.addItem(f"[{idx}] {name}", idx)
        except Exception:
            log.warning("Could not enumerate audio devices", exc_info=True)
        self._mic_combo.setToolTip(
            "The audio input device used for recording.\n"
            "Select your microphone from the list, or leave as System default."
        )
        audio_form.addRow("Microphone:", self._mic_combo)

        layout.addWidget(audio_section)

        # ── UX Behavior section ──────────────────────────────────────────────
        ux_section, ux_form = make_section("UX Behavior", self)

        self._auto_copy = ToggleSwitch("")
        self._auto_copy.setToolTip(
            "Automatically copies the transcribed text to your clipboard\n"
            "after each recording completes."
        )
        ux_form.addRow(make_toggle_row("Auto-copy transcription to clipboard", self._auto_copy))

        self._auto_paste = ToggleSwitch("")
        self._auto_paste.setToolTip(
            "Simulates a Ctrl+V keypress after copying, pasting the finalized text\n"
            "directly into whatever application is currently focused."
        )
        ux_form.addRow(make_toggle_row("Auto-paste after copy", self._auto_paste))

        self._hotkeys_enabled = ToggleSwitch("")
        self._hotkeys_enabled.setToolTip(
            "Allows the record hotkey to trigger even when SpeakEasy\n"
            "is not the focused window (runs in the background)."
        )
        ux_form.addRow(make_toggle_row("Enable global hotkeys", self._hotkeys_enabled))

        self._streaming_partials = ToggleSwitch("")
        _streaming_tip = (
            "Shows a low-latency preview while speaking. Copy/paste happens\n"
            "only when the final transcription is complete."
        )
        if VARIANT == "cpu":
            _streaming_tip += (
                "\n\nNote: on CPU builds each chunk takes longer to render\n"
                "than on GPU; disable this if your machine is slow."
            )
        self._streaming_partials.setToolTip(_streaming_tip)
        ux_form.addRow(make_toggle_row("Live transcription", self._streaming_partials))
        self._streaming_description = QLabel(
            "Shows a low-latency preview while speaking. Copy/paste happens only when "
            "the final transcription is complete."
        )
        self._streaming_description.setWordWrap(True)
        self._streaming_description.setStyleSheet(f"color: {Color.TEXT_MUTED};")
        ux_form.addRow(self._streaming_description)

        layout.addWidget(ux_section)

        # ── Hotkeys section ──────────────────────────────────────────────────
        hk_section, hk_form = make_section("Hotkeys", self)

        self._hotkey_start = QLineEdit()
        self._hotkey_start.setToolTip(
            "Keyboard shortcut to start and stop recording.\n"
            "Format: modifier+key, e.g. ctrl+alt+p or ctrl+shift+r.\n"
            "Requires global hotkeys to be enabled."
        )
        hk_form.addRow("Record hotkey:", self._hotkey_start)

        self._hotkey_quit = QLineEdit()
        self._hotkey_quit.setToolTip(
            "Keyboard shortcut to close SpeakEasy from anywhere.\n"
            "Format: modifier+key, e.g. ctrl+alt+q."
        )
        hk_form.addRow("Quit hotkey:", self._hotkey_quit)

        self._hotkey_dev_panel = QLineEdit()
        self._hotkey_dev_panel.setToolTip(
            "Keyboard shortcut to toggle the Developer Panel.\n"
            "Format: modifier+key, e.g. ctrl+alt+d."
        )
        hk_form.addRow("Dev Panel hotkey:", self._hotkey_dev_panel)

        layout.addWidget(hk_section)

        # ── Action row ───────────────────────────────────────────────────────
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, Spacing.LG, 0, 0)
        self._btn_apply = QPushButton("Apply")
        self._btn_apply.setEnabled(False)
        self._btn_apply.setToolTip("Apply pending changes")
        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_restore = QPushButton("Restore Defaults")
        self._btn_restore.setStyleSheet(ghost_button_style())
        self._btn_restore.clicked.connect(self._on_restore_defaults)
        action_row.addWidget(self._btn_apply)
        action_row.addWidget(self._btn_restore)
        action_row.addStretch()
        layout.addLayout(action_row)

        layout.addStretch()

    # ── Populate ─────────────────────────────────────────────────────────────

    def _populate(self) -> None:
        s = self.settings
        idx = self._device_combo.findText(s.device)
        if idx >= 0:
            self._device_combo.setCurrentIndex(idx)
        idx = self._language_combo.findData(s.language)
        if idx >= 0:
            self._language_combo.setCurrentIndex(idx)
        idx = self._task_combo.findData(s.speech_task)
        if idx >= 0:
            self._task_combo.setCurrentIndex(idx)
        idx = self._translation_target.findData(s.translation_target_language)
        if idx >= 0:
            self._translation_target.setCurrentIndex(idx)
        self._keyword_bias.setText(s.keyword_bias)
        self._punctuation.setChecked(s.punctuation)
        idx = self._formatting_style.findData(s.formatting_style)
        if idx >= 0:
            self._formatting_style.setCurrentIndex(idx)
        self._auto_copy.setChecked(s.auto_copy)
        self._auto_paste.setChecked(s.auto_paste)
        self._hotkeys_enabled.setChecked(s.hotkeys_enabled)
        self._hotkey_start.setText(s.hotkey_start)
        self._hotkey_quit.setText(s.hotkey_quit)
        self._hotkey_dev_panel.setText(s.hotkey_dev_panel)
        self._streaming_partials.setChecked(s.streaming_partials_enabled)

        idx = self._mic_combo.findData(s.mic_device_index)
        if idx >= 0:
            self._mic_combo.setCurrentIndex(idx)

        self._on_device_changed(self._device_combo.currentText())
        self._on_task_changed()

    # ── Auto-apply wiring ────────────────────────────────────────────────────

    def _wire_auto_apply(self) -> None:
        # All fields deferred — just track dirty state until Apply is clicked
        self._language_combo.currentIndexChanged.connect(self._on_any_changed)
        self._task_combo.currentIndexChanged.connect(self._on_task_changed)
        self._translation_target.currentIndexChanged.connect(self._on_any_changed)
        self._keyword_bias.textChanged.connect(self._on_any_changed)
        self._punctuation.toggled.connect(self._on_any_changed)
        self._formatting_style.currentIndexChanged.connect(self._on_any_changed)
        self._auto_copy.toggled.connect(self._on_any_changed)
        self._auto_paste.toggled.connect(self._on_any_changed)
        self._hotkeys_enabled.toggled.connect(self._on_any_changed)
        self._hotkey_start.textChanged.connect(self._on_any_changed)
        self._hotkey_quit.textChanged.connect(self._on_any_changed)
        self._hotkey_dev_panel.textChanged.connect(self._on_any_changed)
        self._streaming_partials.toggled.connect(self._on_any_changed)
        self._mic_combo.currentIndexChanged.connect(self._on_any_changed)
        self._device_combo.currentTextChanged.connect(self._on_any_changed)

    def _on_any_changed(self, *_) -> None:
        self._btn_apply.setEnabled(self._has_any_diff())
        self.risky_change_pending.emit()

    def _has_any_diff(self) -> bool:
        s = self._snapshot
        return (
            self._device_combo.currentText() != s.get("device")
            or self._language_combo.currentData() != s.get("language")
            or self._task_combo.currentData() != s.get("speech_task")
            or self._translation_target.currentData() != s.get("translation_target_language")
            or self._keyword_bias.text().strip() != s.get("keyword_bias")
            or self._punctuation.isChecked() != s.get("punctuation")
            or self._formatting_style.currentData() != s.get("formatting_style")
            or self._auto_copy.isChecked() != s.get("auto_copy")
            or self._auto_paste.isChecked() != s.get("auto_paste")
            or self._hotkeys_enabled.isChecked() != s.get("hotkeys_enabled")
            or (self._hotkey_start.text().strip() or "ctrl+alt+p") != s.get("hotkey_start")
            or (self._hotkey_quit.text().strip() or "ctrl+alt+q") != s.get("hotkey_quit")
            or (self._hotkey_dev_panel.text().strip() or "ctrl+alt+d") != s.get("hotkey_dev_panel")
            or self._streaming_partials.isChecked() != s.get("streaming_partials_enabled")
            or self._mic_combo.currentData() != s.get("mic_device_index")
        )

    def _on_apply(self) -> None:
        old_device = self._snapshot.get("device")

        s = self.settings
        s.device = self._device_combo.currentText()
        s.language = self._language_combo.currentData() or "en"
        s.speech_task = self._task_combo.currentData() or "transcribe"
        s.translation_target_language = self._translation_target.currentData() or "English"
        s.keyword_bias = self._keyword_bias.text().strip()
        s.punctuation = self._punctuation.isChecked()
        s.formatting_style = self._formatting_style.currentData() or "sentence_case"
        s.auto_copy = self._auto_copy.isChecked()
        s.auto_paste = self._auto_paste.isChecked()
        s.hotkeys_enabled = self._hotkeys_enabled.isChecked()
        s.hotkey_start = self._hotkey_start.text().strip() or "ctrl+alt+p"
        s.hotkey_quit = self._hotkey_quit.text().strip() or "ctrl+alt+q"
        s.hotkey_dev_panel = self._hotkey_dev_panel.text().strip() or "ctrl+alt+d"
        s.streaming_partials_enabled = self._streaming_partials.isChecked()
        s.mic_device_index = self._mic_combo.currentData()
        s.save()

        self._snapshot = self._take_snapshot()
        self._btn_apply.setEnabled(False)
        self.settings_applied.emit()

        if s.device != old_device:
            self.reload_model_requested.emit()

    def _on_device_changed(self, device: str) -> None:
        cuda_blocked = VARIANT == "cpu" and device == "cuda"
        self._device_warning.setVisible(cuda_blocked)
        self._btn_apply.setEnabled(not cuda_blocked and self._has_any_diff())

    def _on_task_changed(self, *_) -> None:
        is_translation = self._task_combo.currentData() == "translate"
        self._translation_target.setVisible(is_translation)
        if self._translation_target_label is not None:
            self._translation_target_label.setVisible(is_translation)
        self._on_any_changed()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _on_restore_defaults(self) -> None:
        """Reset fields to their default values (requires Apply to save)."""
        defaults = Settings()
        self._device_combo.setCurrentIndex(
            max(0, self._device_combo.findText(defaults.device))
        )
        self._language_combo.setCurrentIndex(
            max(0, self._language_combo.findData(defaults.language))
        )
        self._task_combo.setCurrentIndex(
            max(0, self._task_combo.findData(defaults.speech_task))
        )
        self._translation_target.setCurrentIndex(
            max(0, self._translation_target.findData(defaults.translation_target_language))
        )
        self._keyword_bias.setText(defaults.keyword_bias)
        self._punctuation.setChecked(defaults.punctuation)
        self._formatting_style.setCurrentIndex(
            max(0, self._formatting_style.findData(defaults.formatting_style))
        )
        self._auto_copy.setChecked(defaults.auto_copy)
        self._auto_paste.setChecked(defaults.auto_paste)
        self._hotkeys_enabled.setChecked(defaults.hotkeys_enabled)
        self._hotkey_start.setText(defaults.hotkey_start)
        self._hotkey_quit.setText(defaults.hotkey_quit)
        self._hotkey_dev_panel.setText(defaults.hotkey_dev_panel)
        self._streaming_partials.setChecked(defaults.streaming_partials_enabled)


class AdvancedSettingsWidget(QWidget):
    """Embeddable developer/runtime settings UI — all fields are deferred."""

    risky_change_pending = Signal()
    settings_applied = Signal()
    reload_model_requested = Signal()

    def __init__(self, settings: Settings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(500)
        self.settings = settings
        self._snapshot = self._take_snapshot()
        self._build_ui()
        self._populate()
        self._wire_auto_apply()

    def _take_snapshot(self) -> dict:
        return {f.name: getattr(self.settings, f.name) for f in dc_fields(self.settings.__class__)
                if not f.name.startswith("_")}

    def _build_ui(self) -> None:
        from .theme import Color, Spacing, ghost_button_style, make_section, make_toggle_row
        from .main_window import ToggleSwitch

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.SECTION)

        runtime_section, runtime_form = make_section("Model Runtime", self)

        model_row = QHBoxLayout()
        self._model_path = QLineEdit()
        self._model_path.setToolTip(
            "Folder containing the downloaded model weights.\n"
            "Use Browse to locate the directory on disk."
        )
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self._browse_model_path)
        model_row.addWidget(self._model_path)
        model_row.addWidget(btn_browse)
        runtime_form.addRow("Model path:", model_row)

        self._inference_timeout = QSpinBox()
        self._inference_timeout.setRange(5, 300)
        self._inference_timeout.setSuffix(" s")
        self._inference_timeout.setToolTip(
            "Maximum time (in seconds) to wait for a transcription to finish\n"
            "before giving up. Increase this if long recordings are timing out."
        )
        runtime_form.addRow("Inference timeout:", self._inference_timeout)

        layout.addWidget(runtime_section)

        segmentation_section, segmentation_form = make_section("Audio Segmentation", self)

        self._silence_threshold = QDoubleSpinBox()
        self._silence_threshold.setRange(0.0001, 0.1)
        self._silence_threshold.setDecimals(4)
        self._silence_threshold.setSingleStep(0.0005)
        self._silence_threshold.setToolTip(
            "How quiet the audio must be to count as silence and stop recording.\n"
            "Lower value = more sensitive. Higher value = requires more obvious silence."
        )
        segmentation_form.addRow("Silence threshold (RMS):", self._silence_threshold)

        self._silence_margin = QSpinBox()
        self._silence_margin.setRange(50, 1000)
        self._silence_margin.setSuffix(" ms")
        self._silence_margin.setToolTip(
            "Extra time to continue recording after silence is detected.\n"
            "Increase this if the end of your sentences is being clipped."
        )
        segmentation_form.addRow("Silence margin:", self._silence_margin)

        self._sample_rate = QSpinBox()
        self._sample_rate.setRange(8000, 48000)
        self._sample_rate.setSingleStep(8000)
        self._sample_rate.setSuffix(" Hz")
        self._sample_rate.setToolTip(
            "Recording sample rate. Granite examples use mono audio at 16000 Hz;\n"
            "keep the default unless you are diagnosing device-specific audio issues."
        )
        segmentation_form.addRow("Sample rate:", self._sample_rate)

        layout.addWidget(segmentation_section)

        diagnostics_section, diagnostics_form = make_section("Diagnostics", self)

        self._clear_logs_on_exit = ToggleSwitch("")
        self._clear_logs_on_exit.setToolTip(
            "Erases the contents of the diagnostic log panel\n"
            "each time the application closes."
        )
        diagnostics_form.addRow(make_toggle_row("Clear logs on application exit", self._clear_logs_on_exit))
        diagnostics_note = QLabel("Runtime and diagnostic controls are intended for troubleshooting.")
        diagnostics_note.setWordWrap(True)
        diagnostics_note.setStyleSheet(f"color: {Color.TEXT_MUTED};")
        diagnostics_form.addRow(diagnostics_note)

        layout.addWidget(diagnostics_section)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, Spacing.LG, 0, 0)
        self._btn_apply = QPushButton("Apply")
        self._btn_apply.setEnabled(False)
        self._btn_apply.setToolTip("Apply pending changes")
        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_restore = QPushButton("Restore Defaults")
        self._btn_restore.setStyleSheet(ghost_button_style())
        self._btn_restore.clicked.connect(self._on_restore_defaults)
        action_row.addWidget(self._btn_apply)
        action_row.addWidget(self._btn_restore)
        action_row.addStretch()
        layout.addLayout(action_row)

        layout.addStretch()

    def _populate(self) -> None:
        s = self.settings
        self._model_path.setText(s.model_path)
        self._inference_timeout.setValue(s.inference_timeout)
        self._silence_threshold.setValue(s.silence_threshold)
        self._silence_margin.setValue(s.silence_margin_ms)
        self._sample_rate.setValue(s.sample_rate)
        self._clear_logs_on_exit.setChecked(s.clear_logs_on_exit)

    def _wire_auto_apply(self) -> None:
        self._model_path.textChanged.connect(self._on_any_changed)
        self._inference_timeout.valueChanged.connect(self._on_any_changed)
        self._silence_threshold.valueChanged.connect(self._on_any_changed)
        self._silence_margin.valueChanged.connect(self._on_any_changed)
        self._sample_rate.valueChanged.connect(self._on_any_changed)
        self._clear_logs_on_exit.toggled.connect(self._on_any_changed)

    def _on_any_changed(self, *_) -> None:
        self._btn_apply.setEnabled(self._has_any_diff())
        self.risky_change_pending.emit()

    def _has_any_diff(self) -> bool:
        s = self._snapshot
        return (
            self._model_path.text().strip() != s.get("model_path")
            or self._inference_timeout.value() != s.get("inference_timeout")
            or self._silence_threshold.value() != s.get("silence_threshold")
            or self._silence_margin.value() != s.get("silence_margin_ms")
            or self._sample_rate.value() != s.get("sample_rate")
            or self._clear_logs_on_exit.isChecked() != s.get("clear_logs_on_exit")
        )

    def _on_apply(self) -> None:
        old_model_path = self._snapshot.get("model_path")

        s = self.settings
        s.model_path = self._model_path.text().strip()
        s.inference_timeout = self._inference_timeout.value()
        s.silence_threshold = self._silence_threshold.value()
        s.silence_margin_ms = self._silence_margin.value()
        s.sample_rate = self._sample_rate.value()
        s.clear_logs_on_exit = self._clear_logs_on_exit.isChecked()
        s.save()

        self._snapshot = self._take_snapshot()
        self._btn_apply.setEnabled(False)
        self.settings_applied.emit()

        if s.model_path != old_model_path:
            self.reload_model_requested.emit()

    def _browse_model_path(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Model Directory",
            self._model_path.text(),
        )
        if path:
            self._model_path.setText(path)

    def _on_restore_defaults(self) -> None:
        defaults = Settings()
        self._model_path.setText(defaults.model_path)
        self._inference_timeout.setValue(defaults.inference_timeout)
        self._silence_threshold.setValue(defaults.silence_threshold)
        self._silence_margin.setValue(defaults.silence_margin_ms)
        self._sample_rate.setValue(defaults.sample_rate)
        self._clear_logs_on_exit.setChecked(defaults.clear_logs_on_exit)


class SettingsDialog(QDialog):
    """Backwards-compat shim — wraps SettingsWidget in a modal dialog so any
    legacy callers keep working. New code should embed SettingsWidget directly."""

    def __init__(self, settings: Settings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        self._widget = SettingsWidget(settings, self)
        layout.addWidget(self._widget)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
