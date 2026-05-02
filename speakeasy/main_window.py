"""
Main application window for SpeakEasy AI.

Integrates model engine lifecycle, audio recording, transcription,
clipboard, hotkeys, and history into a single cohesive window.
"""

from __future__ import annotations

import datetime
import logging
import os
import sys
import time
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPropertyAnimation, QRect, QThreadPool, QTimer, Qt, Property, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QToolButton,
    QWidget,
)

import numpy as np

from .audio import AudioRecorder, play_beep
from .clipboard import set_clipboard_text, simulate_paste
from ._constants import (
    LOADING_TICK_MS,
    METRICS_POLL_MS,
    PBT_APMRESUMEAUTOMATIC,
    PBT_APMRESUMESUSPEND,
    STATE_RESET_ERROR_MS,
    STATE_RESET_IDLE_MS,
    SYSTEM_RESUME_DEBOUNCE_S,
    SYSTEM_RESUME_DELAY_MS,
    WM_HOTKEY,
    WM_POWERBROADCAST,
)
from .config import DEFAULT_LOG_DIR, DEFAULT_PRESETS_DIR, Settings
from ._build_variant import VARIANT
from .engine import ENGINES
from .engine.granite_transcribe import GraniteTranscribeEngine
from .hotkeys import HotkeyManager
from ._resource_monitor import ResourceMonitor
from .pro_preset import ProPreset, bootstrap_presets, load_all_presets
from .status_pills import ProMode, StatusPillBar
from .text_processor import TextProcessor, load_api_key_from_keyring
from .workers import DedicatedWorkerPool, Worker

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .developer_panel import DeveloperPanel


# ── Qt-compatible log handler ─────────────────────────────────────────────────


class _QtLogEmitter(QObject):
    log_signal = Signal(str)


class QtLogHandler(logging.Handler):
    """Routes log records to a Qt signal for display in the log panel."""

    def __init__(self) -> None:
        super().__init__()
        self.emitter = _QtLogEmitter()

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.emitter.log_signal.emit(msg)


# ── State enums ───────────────────────────────────────────────────────────────


class DictationState(str, Enum):
    IDLE = "Idle"
    RECORDING = "Recording…"
    PROCESSING = "Processing…"
    SUCCESS = "Success"
    ERROR = "Error"

    @property
    def display(self) -> str:
        return _DICTATION_STATE_DISPLAY[self]


class ModelStatus(str, Enum):
    NOT_LOADED = "Not loaded"
    LOADING = "Loading…"
    READY = "Ready"
    VALIDATING = "Validating…"
    VALIDATED = "Validated"
    ERROR = "Error"

    @property
    def display(self) -> str:
        return _MODEL_STATUS_DISPLAY[self]


_DICTATION_STATE_DISPLAY = {
    DictationState.IDLE: "Idle",
    DictationState.RECORDING: "Recording",
    DictationState.PROCESSING: "Transcribing",
    DictationState.SUCCESS: "Complete",
    DictationState.ERROR: "Error",
}


_MODEL_STATUS_DISPLAY = {
    ModelStatus.NOT_LOADED: "Not loaded",
    ModelStatus.LOADING: "Loading",
    ModelStatus.READY: "Ready",
    ModelStatus.VALIDATING: "Validating",
    ModelStatus.VALIDATED: "Ready",
    ModelStatus.ERROR: "Error",
}


# ── Toggle switch widget ──────────────────────────────────────────────────────


class ToggleSwitch(QAbstractButton):
    """A modern oval toggle switch that replaces QCheckBox.

    Drop-in replacement: supports setChecked(), isChecked(), and the
    toggled(bool) signal inherited from QAbstractButton.
    """

    from .theme import Color as _TC, Motion as _TM, Spacing as _TS
    _TRACK_ON  = QColor(_TC.PRIMARY)
    _TRACK_OFF = QColor(_TC.BORDER_SUBTLE)
    _KNOB      = QColor("#ffffff")
    _TRACK_W   = 38   # within spec range 36-40
    _TRACK_H   = 22   # within spec range 20-22
    _KNOB_D    = 16   # knob diameter (proportional: ~73% of track height)

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        # Animated knob x-position: 0.0 = off (left), 1.0 = on (right)
        self._knob_pos: float = 1.0 if self.isChecked() else 0.0

        self._anim = QPropertyAnimation(self, b"knob_pos", self)
        self._anim.setDuration(self._TM.DURATION_FAST_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self.toggled.connect(self._on_toggled)

    # ── Qt property for animation ─────────────────────────────────────────────

    def _get_knob_pos(self) -> float:
        return self._knob_pos

    def _set_knob_pos(self, value: float) -> None:
        self._knob_pos = value
        self.update()

    knob_pos = Property(float, _get_knob_pos, _set_knob_pos)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_toggled(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._knob_pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    # ── Sizing ────────────────────────────────────────────────────────────────

    def sizeHint(self):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QFontMetrics
        text_w = QFontMetrics(self.font()).horizontalAdvance(self.text())
        gap = 8 if self.text() else 0
        return QSize(self._TRACK_W + gap + text_w, max(self._TRACK_H, 22))

    # ── Painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Track ─────────────────────────────────────────────────────────────
        track_color = QColor(
            int(self._TRACK_OFF.red()   + self._knob_pos * (self._TRACK_ON.red()   - self._TRACK_OFF.red())),
            int(self._TRACK_OFF.green() + self._knob_pos * (self._TRACK_ON.green() - self._TRACK_OFF.green())),
            int(self._TRACK_OFF.blue()  + self._knob_pos * (self._TRACK_ON.blue()  - self._TRACK_OFF.blue())),
        )
        track_rect = QRect(0, (self.height() - self._TRACK_H) // 2,
                           self._TRACK_W, self._TRACK_H)
        path = QPainterPath()
        path.addRoundedRect(track_rect, self._TRACK_H / 2, self._TRACK_H / 2)
        p.fillPath(path, track_color)

        # ── Knob ──────────────────────────────────────────────────────────────
        margin = (self._TRACK_H - self._KNOB_D) // 2
        travel = self._TRACK_W - self._KNOB_D - 2 * margin
        knob_x = int(margin + self._knob_pos * travel)
        knob_y = (self.height() - self._KNOB_D) // 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._KNOB)
        p.drawEllipse(knob_x, knob_y, self._KNOB_D, self._KNOB_D)

        # ── Label text ────────────────────────────────────────────────────────
        if self.text():
            p.setPen(QPen(QColor("#cccccc")))
            text_x = self._TRACK_W + self._TS.SM
            text_rect = QRect(text_x, 0, self.width() - text_x, self.height())
            p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       self.text())

        p.end()


# ═════════════════════════════════════════════════════════════════════════════
# Main Window
# ═════════════════════════════════════════════════════════════════════════════


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(self, settings: Settings, engine=None, engine_pool=None):
        super().__init__()
        self.settings = settings
        self._dev_panel: Optional["DeveloperPanel"] = None
        self._log_buffer: list[str] = []  # holds lines until panel exists
        self._pool = QThreadPool.globalInstance()
        self._engine_pool = engine_pool if engine_pool is not None else DedicatedWorkerPool(self)
        self._engine_pool.setMaxThreadCount(1)
        self._engine_pool.setExpiryTimeout(-1)

        # ── Engine ───────────────────────────────────────────────────────────
        if engine is not None:
            self._engine = engine
        else:
            self._engine = GraniteTranscribeEngine()

        # ── Audio ────────────────────────────────────────────────────────────
        self._recorder = AudioRecorder(
            sample_rate=settings.sample_rate,
            silence_threshold=settings.silence_threshold,
            silence_margin_ms=settings.silence_margin_ms,
            device=settings.mic_device_index if settings.mic_device_index >= 0 else None,
        )
        self._hotkey_mgr = HotkeyManager(parent=self)

        # ── State ────────────────────────────────────────────────────────────
        self._dictation_state = DictationState.IDLE
        self._model_status = ModelStatus.NOT_LOADED
        self._device_fallback_to_cpu: bool = False
        self._model_load_start: float = 0.0
        self._last_resume_time: float = 0.0
        self._mic_suspended_for_processing = False
        # Live-draft history entry updated while the engine transcribes a
        # multi-chunk recording; None outside of transcription.
        self._active_draft_entry = None
        # Buffer for history entries added before the Developer Panel exists.
        self._history_buffer: list[tuple] = []

        # ── Resource monitor ─────────────────────────────────────────────────
        self._res_monitor = ResourceMonitor(
            pool=self._pool, interval_ms=METRICS_POLL_MS, parent=self,
        )
        self._res_monitor.metrics_updated.connect(self._on_metrics_result)
        self._res_monitor.metrics_error.connect(
            lambda err: log.error("Metrics poll error: %s", err)
        )

        # ── Professional Mode ────────────────────────────────────────────────
        self._api_key: str = ""
        self._text_processor: Optional[TextProcessor] = None
        self._pro_worker: Optional[Worker] = None
        self._pro_context: Optional[tuple[str, str]] = None  # (ts, original)
        self._pro_timeout: Optional[QTimer] = None
        self._pro_presets: dict[str, ProPreset] = {}
        self._active_preset: Optional[ProPreset] = None

        # Bootstrap presets directory and load presets
        bootstrap_presets(DEFAULT_PRESETS_DIR)
        self._pro_presets = load_all_presets(DEFAULT_PRESETS_DIR)
        self._active_preset = self._pro_presets.get(settings.pro_active_preset)

        if settings.store_api_key:
            self._api_key = load_api_key_from_keyring()
        if settings.professional_mode and self._api_key and self._active_preset:
            self._text_processor = TextProcessor(
                api_key=self._api_key,
                model=self._active_preset.model or "gpt-5.4-mini",
            )
        elif settings.professional_mode and not self._api_key:
            log.warning("Professional Mode enabled but no API key configured")

        # ── Build UI ─────────────────────────────────────────────────────────
        self.setWindowTitle("SpeakEasy AI Granite — Voice to Text")
        self.setMinimumSize(640, 600)
        self.resize(720, 640)
        self._build_ui()
        self._setup_logging()
        self._setup_timers()
        self._connect_hotkeys()

        # ── Open mic stream ──────────────────────────────────────────────────
        try:
            self._recorder.open_stream()
            self._log_ui("Microphone stream opened")
        except Exception as exc:
            self._log_ui(f"Microphone error: {exc}", error=True)

        # ── Begin model loading ──────────────────────────────────────────────
        if self._granite_model_ready():
            self._load_model()
        else:
            log.warning("Granite model not found at %s", self.settings.model_path)
            self._set_model_status(ModelStatus.ERROR)
            self._log_ui("Model not found — setup required", error=True)
            # Defer dialog to after the event loop starts so the window is visible
            QTimer.singleShot(500, self._prompt_model_setup_on_start)

    # ═════════════════════════════════════════════════════════════════════════
    # UI CONSTRUCTION
    # ═════════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        from PySide6.QtCore import QSize
        from .theme import (
            Color,
            Font,
            Size,
            Spacing,
            gear_button_style,
            ghost_button_style,
            load_icon,
            make_bounded_content,
            make_section_panel,
            make_setting_row,
            primary_record_button_style,
            subtle_danger_button_style,
        )

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        root.setSpacing(Spacing.MD)

        # ── Transcription section (dominant) ─────────────────────────────────
        self._btn_record = QPushButton()
        self._btn_record.setMinimumHeight(Size.BUTTON_HEIGHT_PRIMARY)
        self._btn_record.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_record.setStyleSheet(primary_record_button_style("idle"))
        self._btn_record.clicked.connect(self._on_toggle_recording)

        record_button_layout = QHBoxLayout(self._btn_record)
        record_button_layout.setContentsMargins(Spacing.MD, 0, Spacing.MD, 0)
        record_button_layout.setSpacing(Spacing.SM)
        record_button_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._record_icon = QLabel()
        icon_size = 26
        self._record_icon.setPixmap(load_icon("microphone-white").pixmap(QSize(icon_size, icon_size)))
        self._record_icon.setFixedSize(icon_size, icon_size)
        self._record_icon.setStyleSheet("background: transparent;")
        self._record_title = QLabel("Start Recording")
        title_font = QFont(Font.FAMILY, 13)
        title_font.setWeight(QFont.Weight.DemiBold)
        self._record_title.setFont(title_font)
        self._record_title.setStyleSheet(f"color: {Color.TEXT_PRIMARY}; background: transparent; font-weight: 700;")
        self._record_dot = QLabel("●")
        status_font = QFont(Font.FAMILY, 10)
        status_font.setWeight(QFont.Weight.DemiBold)
        self._record_dot.setFont(status_font)
        self._record_dot.setStyleSheet(f"color: {Color.SUCCESS}; background: transparent; font-weight: 700;")
        self._record_status = QLabel("Ready")
        self._record_status.setFont(status_font)
        self._record_status.setStyleSheet(f"color: {Color.TEXT_PRIMARY}; background: transparent; font-weight: 600;")
        record_button_layout.addWidget(self._record_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        record_button_layout.addWidget(self._record_title, 0, Qt.AlignmentFlag.AlignVCenter)
        record_button_layout.addWidget(self._record_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        record_button_layout.addWidget(self._record_status, 0, Qt.AlignmentFlag.AlignVCenter)

        # Record button + Developer Panel settings button, full-width and responsive.
        record_row_widget = QWidget(central)
        record_row_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        record_row = QHBoxLayout(record_row_widget)
        record_row.setContentsMargins(0, 0, 0, 0)
        record_row.setSpacing(Spacing.SM)
        record_row.addWidget(self._btn_record)

        self._btn_dev_panel = QToolButton()
        self._btn_dev_panel.setText("Settings")
        self._btn_dev_panel.setIcon(load_icon("settings"))
        self._btn_dev_panel.setIconSize(QSize(22, 22))
        self._btn_dev_panel.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self._btn_dev_panel.setToolTip("Open Developer Panel")
        self._btn_dev_panel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_dev_panel.setMinimumSize(Size.GEAR_BUTTON, Size.BUTTON_HEIGHT_PRIMARY)
        self._btn_dev_panel.setMaximumSize(16777215, Size.BUTTON_HEIGHT_PRIMARY)
        self._btn_dev_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._btn_dev_panel.setStyleSheet(gear_button_style())
        self._btn_dev_panel.setCheckable(True)
        self._btn_dev_panel.clicked.connect(self._on_toggle_dev_panel)
        record_row.addWidget(self._btn_dev_panel)
        record_row.setStretch(0, 5)
        record_row.setStretch(1, 1)
        root.addWidget(record_row_widget)

        # ── Status indicators (model + dictation + professional mode) ───────
        self._status_bar = StatusPillBar(self)
        self._status_bar.ai_model_clicked.connect(self._on_open_settings)
        self._status_bar.pro_mode_clicked.connect(self._on_open_pro_settings)
        root.addWidget(self._status_bar)
        self._update_global_status()
        self._refresh_dictation_buttons()

        # ── Automation ───────────────────────────────────────────────────────
        automation_section, automation_layout = make_section_panel("Automation", central, icon_name="keyboard")
        self._chk_auto_copy = ToggleSwitch()
        self._chk_auto_copy.setChecked(self.settings.auto_copy)
        self._chk_auto_paste = ToggleSwitch()
        self._chk_auto_paste.setChecked(self.settings.auto_paste)
        self._chk_hotkeys = ToggleSwitch()
        self._chk_hotkeys.setChecked(self.settings.hotkeys_enabled)
        self._chk_hotkeys.toggled.connect(self._on_hotkeys_toggled)
        automation_layout.addWidget(make_setting_row("Auto-copy to clipboard", self._chk_auto_copy, automation_section))
        automation_layout.addWidget(make_setting_row("Auto-paste (Ctrl+V)", self._chk_auto_paste, automation_section))
        automation_layout.addWidget(make_setting_row("Global hotkeys", self._chk_hotkeys, automation_section, show_separator=False))
        root.addWidget(automation_section)

        # ── Transcription Mode ───────────────────────────────────────────────
        transcription_section, transcription_layout = make_section_panel("Transcription Mode", central, icon_name="sparkles")
        self._chk_professional = ToggleSwitch()
        self._chk_professional.setFixedSize(38, 22)
        self._chk_professional.setChecked(self.settings.professional_mode)
        self._chk_professional.toggled.connect(self._on_professional_toggled)
        self._combo_pro_preset = QComboBox()
        self._combo_pro_preset.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._combo_pro_preset.setEnabled(self.settings.professional_mode)
        self._populate_pro_preset_combo()
        self._combo_pro_preset.currentTextChanged.connect(self._on_pro_preset_quick_select)
        transcription_layout.addWidget(make_setting_row("Enable Professional Mode", self._chk_professional, transcription_section))

        profile_row = QWidget(transcription_section)
        profile_row.setFixedHeight(Size.INPUT_HEIGHT)
        profile_row_layout = QHBoxLayout(profile_row)
        profile_row_layout.setContentsMargins(0, 0, 0, 0)
        profile_row_layout.setSpacing(Spacing.SM)
        profile_label = QLabel("Profile")
        profile_label.setStyleSheet(f"color: {Color.TEXT_HEADING}; background: transparent; font-weight: 600;")
        profile_row_layout.addWidget(profile_label, 0, Qt.AlignmentFlag.AlignVCenter)
        profile_row_layout.addWidget(self._combo_pro_preset, 1, Qt.AlignmentFlag.AlignVCenter)
        transcription_layout.addWidget(profile_row)
        root.addWidget(transcription_section)

        # ── Hidden metric labels (updated by _on_metrics_result / _set_model_status,
        #    forwarded to the Developer Panel when open) ──────────────────────
        self._lbl_engine = QLabel()
        self._lbl_model_status = QLabel()
        self._lbl_ram = QLabel()
        self._pb_ram = QProgressBar()
        self._lbl_vram = QLabel()
        self._pb_vram = QProgressBar()
        self._lbl_gpu_info = QLabel()
        self._log_text = QPlainTextEdit()
        self._log_text.setMaximumBlockCount(500)

        # ── Bottom buttons ───────────────────────────────────────────────────
        bottom_content, bottom_content_layout, bottom_outer = make_bounded_content(central)
        bottom_content_layout.setSpacing(0)
        bottom_row_widget = QWidget(bottom_content)
        bottom_row = QHBoxLayout(bottom_row_widget)
        bottom_row.setContentsMargins(0, 0, 0, 0)
        btn_history = QPushButton("History")
        btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_history.setStyleSheet(ghost_button_style())
        btn_history.clicked.connect(self._on_show_history)
        btn_quit = QPushButton("Quit")
        btn_quit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_quit.setStyleSheet(subtle_danger_button_style())
        btn_quit.clicked.connect(self.close)
        bottom_row.addWidget(btn_history)
        bottom_row.addStretch()
        bottom_row.addWidget(btn_quit)
        bottom_content_layout.addWidget(bottom_row_widget)
        root.addLayout(bottom_outer)

        # ── Global aesthetics ────────────────────────────────────────────────
        from .theme import Font
        QApplication.setFont(QFont(Font.FAMILY, Font.BODY[0]))

        if self.settings.dev_panel_open:
            # Defer so the main window is laid out before we snap to it
            QTimer.singleShot(0, self._on_toggle_dev_panel)

    def _update_global_status(self) -> None:
        """Refresh the unified status bar with model, dictation, and professional mode state."""
        if not hasattr(self, "_status_bar"):
            return

        engine_display = str(getattr(self._engine, "name", "granite")).capitalize()
        device_label = "GPU" if self.settings.device == "cuda" and not self._device_fallback_to_cpu else "CPU"
        self._status_bar.set_ai_model(
            name=engine_display,
            device=device_label,
            status=self._model_status,
            fallback=self._device_fallback_to_cpu,
        )
        self._status_bar.set_dictation(self._dictation_state)

        if self.settings.professional_mode and self._pro_worker is not None:
            pro_mode = ProMode.PROCESSING
            preset_name = self.settings.pro_active_preset
        elif self.settings.professional_mode and self._text_processor is not None:
            pro_mode = ProMode.ACTIVE
            preset_name = self.settings.pro_active_preset
        else:
            pro_mode = ProMode.OFF
            preset_name = None
        self._status_bar.set_pro_mode(pro_mode, preset_name)

    # ═════════════════════════════════════════════════════════════════════════
    # LOGGING INTEGRATION
    # ═════════════════════════════════════════════════════════════════════════

    def _setup_logging(self) -> None:
        handler = QtLogHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", "%H:%M:%S"))
        handler.emitter.log_signal.connect(self._append_log)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)

    @Slot(str)
    def _append_log(self, msg: str) -> None:
        # Write to inline log (while it exists) and to panel
        if hasattr(self, "_log_text"):
            self._log_text.appendPlainText(msg)
        if self._dev_panel is not None:
            self._dev_panel.logs_widget.log_text.append_log_line(msg)
        else:
            self._log_buffer.append(msg)
            if len(self._log_buffer) > 500:
                self._log_buffer = self._log_buffer[-500:]

    def _flush_log_buffer(self) -> None:
        if self._dev_panel is None:
            return
        for line in self._log_buffer:
            self._dev_panel.logs_widget.log_text.append_log_line(line)
        self._log_buffer.clear()

    def _log_ui(self, msg: str, error: bool = False) -> None:
        if error:
            log.error(msg)
        else:
            log.info(msg)

    # ═════════════════════════════════════════════════════════════════════════
    # TIMERS
    # ═════════════════════════════════════════════════════════════════════════

    def _setup_timers(self) -> None:
        # Model loading elapsed timer (updates label during loading)
        self._loading_timer = QTimer(self)
        self._loading_timer.timeout.connect(self._update_loading_label)
        self._loading_timer.setInterval(LOADING_TICK_MS)

        # Start resource-metrics polling
        self._res_monitor.start()

    # ═════════════════════════════════════════════════════════════════════════
    # HOTKEYS
    # ═════════════════════════════════════════════════════════════════════════

    def _connect_hotkeys(self) -> None:
        self._hotkey_mgr.toggle_requested.connect(self._on_toggle_recording)
        self._hotkey_mgr.quit_requested.connect(self.close)
        self._hotkey_mgr.dev_panel_toggle_requested.connect(self._on_toggle_dev_panel)
        if self.settings.hotkeys_enabled:
            # Defer Win32 RegisterHotKey by one event-loop tick so the native
            # window handle (winId) is stable after show().  In PyInstaller
            # frozen builds Qt can recreate the HWND during show(), which
            # silently invalidates a hotkey registered earlier in __init__.
            QTimer.singleShot(0, self._register_hotkeys)

    @Slot()
    def _register_hotkeys(self) -> None:
        """Register Win32 hotkeys against the post-show stable HWND."""
        self._hotkey_mgr.register(
            self.settings.hotkey_start,
            self.settings.hotkey_quit,
            hwnd=int(self.winId()),
            hotkey_dev_panel=self.settings.hotkey_dev_panel,
        )

    @Slot(bool)
    def _on_hotkeys_toggled(self, enabled: bool) -> None:
        if enabled:
            self._hotkey_mgr.register(
                self.settings.hotkey_start,
                self.settings.hotkey_quit,
                hwnd=int(self.winId()),
                hotkey_dev_panel=self.settings.hotkey_dev_panel,
            )
            self._log_ui("Global hotkeys enabled")
        else:
            self._hotkey_mgr.unregister()
            self._log_ui("Global hotkeys disabled")

    # ═════════════════════════════════════════════════════════════════════════
    # MODEL ENGINE MANAGEMENT
    # ═════════════════════════════════════════════════════════════════════════

    def _set_model_status(self, status: ModelStatus) -> None:
        from .theme import Color as TC
        self._model_status = status
        color_map = {
            ModelStatus.READY: TC.SUCCESS,
            ModelStatus.VALIDATED: TC.SUCCESS,
            ModelStatus.LOADING: TC.WARNING,
            ModelStatus.NOT_LOADED: TC.TEXT_MUTED,
            ModelStatus.VALIDATING: TC.INFO,
            ModelStatus.ERROR: TC.DANGER,
        }
        color = color_map.get(status, TC.TEXT_MUTED)
        self._lbl_model_status.setText(
            f'Status: <span style="color:{color}"><b>{status.value}</b></span>'
        )
        if self._dev_panel is not None:
            self._dev_panel.realtime_widget.update_engine_status(
                self._engine.name, self.settings.device, status.value, color,
            )
        self._update_global_status()
        self._refresh_dictation_buttons()

    def _load_model(self) -> None:
        """Begin model loading on a worker thread."""
        self._device_fallback_to_cpu = False
        self._set_model_status(ModelStatus.LOADING)
        self._model_load_start = time.time()
        self._loading_timer.start()
        self._log_ui(f"Loading {self._engine.name} model…")

        def _do_load():
            self._engine.load(self.settings.model_path, self.settings.device)

        worker = Worker(_do_load)
        worker.signals.result.connect(self._on_model_loaded)
        worker.signals.error.connect(self._on_model_load_error)
        self._engine_pool.start(worker)

    @Slot(object)
    def _on_model_loaded(self, _result) -> None:
        self._loading_timer.stop()
        elapsed = time.time() - self._model_load_start
        actual_device = self._actual_engine_device()
        self._device_fallback_to_cpu = (
            self.settings.device == "cuda" and actual_device == "cpu"
        )
        self._set_model_status(ModelStatus.READY)
        device_label = "CPU" if actual_device == "cpu" else "GPU"
        self._lbl_engine.setText(f"Engine: {self._engine.name}  \u00b7  Device: {device_label}")
        self._log_ui(f"Model loaded in {elapsed:.1f}s")

    def _actual_engine_device(self) -> str:
        actual_device = getattr(self._engine, "actual_device", None)
        if actual_device is None:
            actual_device = getattr(self._engine, "device", self.settings.device)
        actual_text = str(actual_device).lower()
        return "cuda" if actual_text.startswith("cuda") else "cpu"

    @Slot(str)
    def _on_model_load_error(self, err: str) -> None:
        self._loading_timer.stop()
        self._set_model_status(ModelStatus.ERROR)
        self._log_ui(f"Model load failed: {err}", error=True)

    def _update_loading_label(self) -> None:
        """Update the status label with elapsed loading time."""
        from .theme import Color as TC
        if self._model_status == ModelStatus.LOADING:
            elapsed = int(time.time() - self._model_load_start)
            self._lbl_model_status.setText(
                f'Status: <span style="color:{TC.WARNING}"><b>Loading… {elapsed}s</b></span>'
            )

    @Slot()
    def _on_reload_model(self) -> None:
        """Unload then reload the model."""
        self._log_ui("Reloading model…")

        def _do_reload():
            self._engine.unload()
            self._engine.load(self.settings.model_path, self.settings.device)

        self._device_fallback_to_cpu = False
        self._set_model_status(ModelStatus.LOADING)
        self._model_load_start = time.time()
        self._loading_timer.start()

        worker = Worker(_do_reload)
        worker.signals.result.connect(self._on_model_loaded)
        worker.signals.error.connect(self._on_model_load_error)
        self._engine_pool.start(worker)

    # ── Resource metrics ──────────────────────────────────────────────────────

    @Slot(object)
    def _on_metrics_result(self, metrics) -> None:
        from .theme import Color as TC

        def _bar_color(pct: float) -> str:
            if pct > 90:
                return TC.DANGER
            if pct > 75:
                return TC.WARNING
            return TC.PRIMARY

        def _bar_style(pct: float) -> str:
            c = _bar_color(pct)
            return (
                f"QProgressBar {{ border: 1px solid {TC.BORDER}; border-radius: 3px; background: {TC.INPUT_BG}; }}"
                f"QProgressBar::chunk {{ background-color: {c}; border-radius: 3px; }}"
            )

        if metrics.ram_total_gb > 0:
            self._lbl_ram.setText(
                f"RAM: {metrics.ram_used_gb:.1f} / {metrics.ram_total_gb:.1f} GB "
                f"({metrics.ram_percent:.0f}%)"
            )
            self._pb_ram.setValue(int(metrics.ram_percent))
            self._pb_ram.setStyleSheet(_bar_style(metrics.ram_percent))
        else:
            self._lbl_ram.setText("RAM: —")
            self._pb_ram.setValue(0)

        gpu = metrics.gpu
        if VARIANT != "cpu" and gpu.vram_total_gb > 0:
            pct = gpu.vram_percent
            vram_text_color = _bar_color(pct)
            self._lbl_vram.setText(
                f'VRAM: <span style="color:{vram_text_color}"><b>{gpu.vram_used_gb:.1f}</b></span>'
                f" / {gpu.vram_total_gb:.1f} GB ({pct:.0f}%)"
            )
            self._pb_vram.setValue(int(pct))
            self._pb_vram.setStyleSheet(_bar_style(pct))
            self._lbl_gpu_info.setText(f"GPU: {gpu.name} ({gpu.temperature_c}°C)")
        else:
            self._lbl_vram.setText("VRAM: —")
            self._pb_vram.setValue(0)
            self._lbl_gpu_info.setText("GPU: —")

        # Forward to Developer Panel
        if self._dev_panel is not None:
            rw = self._dev_panel.realtime_widget
            rw.update_ram(metrics.ram_used_gb, metrics.ram_total_gb, metrics.ram_percent)
            gpu = metrics.gpu
            if VARIANT != "cpu" and gpu.vram_total_gb > 0:
                rw.update_vram(gpu.vram_used_gb, gpu.vram_total_gb, gpu.vram_percent)
                rw.update_gpu(f"{gpu.name} ({gpu.temperature_c}°C)")
            else:
                rw.update_vram(0, 0, 0)
                rw.update_gpu("—")
            # Forward LLM token stats so the sparkline updates continuously
            if self._text_processor is not None:
                tps, ti, to, llm_seq = self._text_processor.token_stats
            else:
                tps, ti, to, llm_seq = 0.0, 0, 0, 0
            rw.update_tokens(tps, ti, to, seq=llm_seq)
            # Forward speech-engine token stats
            if self._engine is not None and hasattr(self._engine, 'token_stats'):
                asr_tps, asr_tot, asr_audio, asr_rtf, asr_seq = self._engine.token_stats
            else:
                asr_tps, asr_tot, asr_audio, asr_rtf, asr_seq = 0.0, 0, 0.0, 0.0, 0
            rw.update_asr_tokens(asr_tps, asr_tot, asr_audio, asr_rtf, seq=asr_seq)

    # —— Validate ——————————————————————————————————————————————————————————————

    @Slot()
    def _on_validate(self) -> None:
        if not self._engine.is_loaded:
            self._log_ui("Cannot validate — model not loaded", error=True)
            return
        self._set_model_status(ModelStatus.VALIDATING)
        self._log_ui("Running functional validation…")

        def _do_validate():
            # Use bundled speech fixture
            fixture_path = Path(__file__).parent / "assets" / "validation.wav"
            if not fixture_path.exists():
                return False, "Validation fixture not found"
            import numpy as np
            import soundfile as sf
            audio, sr = sf.read(fixture_path, dtype="float32")
            if audio.ndim == 2:
                audio = audio[:, 0]
            text = self._engine.transcribe(audio, sr)
            # Loose match — just check for some expected words
            text_lower = text.lower()
            if any(w in text_lower for w in ("testing", "one", "two", "three")):
                return True, f"OK: \"{text}\""
            elif text.strip():
                return True, f"Got text (unexpected): \"{text}\""
            else:
                return False, "Empty transcription result"

        worker = Worker(_do_validate)
        worker.signals.result.connect(self._on_validate_result)
        worker.signals.error.connect(lambda e: self._on_validate_result((False, str(e))))
        self._engine_pool.start(worker)

    @Slot(object)
    def _on_validate_result(self, result: tuple) -> None:
        ok, msg = result
        if ok:
            self._set_model_status(ModelStatus.VALIDATED)
            self._log_ui(f"Validation passed: {msg}")
        else:
            self._set_model_status(ModelStatus.ERROR)
            self._log_ui(f"Validation failed: {msg}", error=True)

    # ═════════════════════════════════════════════════════════════════════════
    # DICTATION
    # ═════════════════════════════════════════════════════════════════════════

    def _set_dictation_state(self, state: DictationState) -> None:
        self._dictation_state = state
        self._update_global_status()
        self._refresh_dictation_buttons()

    def _refresh_dictation_buttons(self) -> None:
        """Enable/disable and relabel the record toggle button based on dictation + model state."""
        is_idle = self._dictation_state == DictationState.IDLE
        is_recording = self._dictation_state == DictationState.RECORDING
        is_processing = self._dictation_state == DictationState.PROCESSING
        model_ready = self._model_status in (ModelStatus.READY, ModelStatus.VALIDATED)
        if is_recording:
            self._btn_record.setEnabled(True)
            self._set_record_button_state("recording")
        elif is_processing:
            self._btn_record.setEnabled(False)
            self._set_record_button_state("processing")
        else:
            self._btn_record.setEnabled(is_idle and model_ready)
            self._set_record_button_state("idle" if model_ready else "disabled")

    def _set_record_button_state(self, state: str) -> None:
        from .theme import Color, primary_record_button_style

        if state == "recording":
            title = "Recording..."
            status = "Recording"
            dot_color = Color.DANGER
        elif state == "processing":
            title = "Transcribing..."
            status = "Please wait"
            dot_color = Color.INFO
        elif state == "disabled":
            title = "Start Recording"
            status = "Please wait"
            dot_color = Color.TEXT_MUTED
        else:
            title = "Start Recording"
            status = "Ready"
            dot_color = Color.SUCCESS

        self._btn_record.setText("")
        self._btn_record.setAccessibleName(f"{title}, {status}")
        self._btn_record.setStyleSheet(primary_record_button_style(state))
        self._record_title.setText(title)
        self._record_dot.setStyleSheet(f"color: {dot_color}; background: transparent; font-weight: 700;")
        self._record_status.setText(status)

    @Slot()
    def _on_toggle_recording(self) -> None:
        """Single hotkey/button handler — start when idle, stop when recording."""
        if self._dictation_state == DictationState.IDLE:
            self._on_start_recording()
        elif self._dictation_state == DictationState.RECORDING:
            self._on_stop_and_transcribe()

    @Slot()
    def _on_start_recording(self) -> None:
        if self._dictation_state != DictationState.IDLE:
            return
        if self._model_status not in (ModelStatus.READY, ModelStatus.VALIDATED):
            self._log_ui("Cannot record — model not ready yet", error=True)
            return
        # Health-check the audio stream before recording
        if not self._recorder.stream_is_alive():
            self._log_ui("Audio stream stale — attempting recovery…")
            if not self._recorder.recover_stream():
                self._log_ui(
                    "Microphone not responding — try changing the audio "
                    "device in Settings",
                    error=True,
                )
                return
            self._log_ui("Audio stream recovered")
        play_beep((600, 900))   # ascending chirp → "go!"
        self._recorder.start_recording()
        self._set_dictation_state(DictationState.RECORDING)
        self._log_ui("Recording started")

    @Slot()
    def _on_stop_and_transcribe(self) -> None:
        """Stop recording, trim, transcribe in-process, clipboard, paste — threaded."""
        if self._dictation_state != DictationState.RECORDING:
            return
        play_beep((900, 500))   # descending chirp → "done"
        self._set_dictation_state(DictationState.PROCESSING)

        # Pause NVML polling — concurrent driver calls can
        # deadlock against CUDA kernel launches in generate().
        self._res_monitor.stop()

        # Wait for any in-flight metrics poll to finish before dispatching
        # the transcription worker (avoids NVML / CUDA overlap).
        import time as _time
        _deadline = _time.monotonic() + 2.0
        while self._res_monitor.is_in_flight and _time.monotonic() < _deadline:
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.processEvents()
            _time.sleep(0.05)

        # Get raw audio (fast, on main thread)
        audio = self._recorder.get_raw_audio()
        if audio is None:
            self._log_ui("No audio recorded", error=True)
            self._res_monitor.start()
            self._set_dictation_state(DictationState.IDLE)
            return

        self._log_ui(f"Recording stopped \u2014 captured {len(audio)/self.settings.sample_rate:.1f}s of audio")

        self._suspend_mic_stream_for_processing()

        # Streaming partial emission: when enabled, the engine fires a
        # callback after each chunk of a multi-chunk transcription. Route it
        # to a Qt signal on the worker (thread-safe via QueuedConnection).
        streaming_enabled = bool(self.settings.streaming_partials_enabled)

        # Heavy work on thread pool — NO clipboard ops here
        def _process(_partial_emit=None):
            # Trim silence
            trim_result = self._recorder.trim_silence(audio)
            if trim_result is None:
                raise RuntimeError("No speech detected — audio was pure silence")
            trimmed, pct = trim_result
            if pct > 1:
                log.info("Trimmed %.0f%% silence", pct)

            # Contiguous copy — trim_silence returns a view/slice that can
            # cause native-code crashes in CUDA / torch.
            trimmed = np.ascontiguousarray(trimmed, dtype=np.float32)

            configure_prompt_options = getattr(self._engine, "configure_prompt_options", None)
            if callable(configure_prompt_options):
                configure_prompt_options(
                    speech_task=self.settings.speech_task,
                    translation_target_language=self.settings.translation_target_language,
                    keyword_bias=self.settings.keyword_bias,
                )

            # Transcribe in-process
            text = self._engine.transcribe(
                trimmed, self.settings.sample_rate, self.settings.language,
                punctuation=self.settings.punctuation,
                timeout=self.settings.inference_timeout,
                partial_callback=_partial_emit,
            )
            return text

        worker = Worker(_process)
        worker.signals.result.connect(self._on_transcription_result)
        worker.signals.error.connect(self._on_transcription_error)
        if streaming_enabled:
            worker.signals.partial.connect(
                self._on_transcription_partial, Qt.ConnectionType.QueuedConnection
            )
            # Bind the worker's partial signal into the _process closure.
            # QueuedConnection ensures the UI slot runs on the main thread.
            worker.args = (worker.signals.partial.emit,)
        self._engine_pool.start(worker)

    @Slot(str, int, int)
    def _on_transcription_partial(self, text: str, chunk_index: int, total_chunks: int) -> None:
        """Engine emitted a per-chunk partial transcription — show as draft."""
        from .history_widget import _HistoryEntry

        text = str(text).strip()
        self._ensure_dev_panel()
        hw = self._dev_panel.history_widget
        if self._active_draft_entry is None:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            draft = _HistoryEntry(
                ts, text, success=True, parent=hw.history_content,
                is_draft=True,
            )
            count = hw.history_layout.count()
            hw.history_layout.insertWidget(max(0, count - 1), draft)
            self._active_draft_entry = draft
        else:
            self._active_draft_entry.set_text(text)
        self._active_draft_entry.set_progress(chunk_index, total_chunks)

    @Slot(object)
    def _on_transcription_result(self, text: str) -> None:
        """Handle transcription result — runs on MAIN THREAD (safe for clipboard)."""
        self._res_monitor.start()
        self._resume_mic_stream_after_processing()
        text = str(text).strip()
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        if text:
            self._set_dictation_state(DictationState.SUCCESS)
            self._log_ui(f"Transcribed: {len(text)} chars")

            # Professional Mode: send to OpenAI for cleanup
            if (
                self.settings.professional_mode
                and self._text_processor is not None
                and self._active_preset is not None
            ):
                self._log_ui("Cleaning up text…")

                preset = self._active_preset

                def _cleanup():
                    result = self._text_processor.process(
                        text,
                        preset=preset,
                    )
                    log.info("Professional cleanup worker finished (%d chars)", len(result))
                    return result

                # Store context for the bound-method handlers so we
                # don't need lambdas (lambdas prevent QObject connection
                # tracking and allow the Worker to be GC'd prematurely).
                self._pro_context = (ts, text)
                self._pro_worker = Worker(_cleanup)
                self._pro_worker.setAutoDelete(False)  # we manage lifetime
                self._pro_worker.signals.result.connect(self._on_professional_result)
                self._pro_worker.signals.error.connect(self._on_professional_error)
                self._pro_worker.signals.finished.connect(self._on_professional_finished)
                self._update_global_status()
                self._pool.start(self._pro_worker)

                # Safety timeout — if signal delivery fails for any
                # reason, fall back after the API timeout + buffer.
                self._pro_timeout = QTimer(self)
                self._pro_timeout.setSingleShot(True)
                self._pro_timeout.timeout.connect(self._on_professional_timeout)
                self._pro_timeout.start(20_000)  # 20 s
                return

            self._add_history(ts, text, success=True)

            copied = True
            if self._chk_auto_copy.isChecked():
                copied = set_clipboard_text(text)  # MAIN THREAD — safe
                if copied:
                    self._log_ui("Copied to clipboard")
                else:
                    self._log_ui("Failed to copy to clipboard", error=True)

            if copied and self._chk_auto_paste.isChecked():
                # Run paste in a thread to avoid blocking UI during modifier wait
                def _paste():
                    simulate_paste(wait_for_modifiers=self._chk_hotkeys.isChecked())
                w = Worker(_paste)
                self._pool.start(w)
        else:
            self._log_ui("Transcription returned empty text")
            self._add_history(ts, "(empty)", success=True)
            self._set_dictation_state(DictationState.SUCCESS)

        QTimer.singleShot(
            STATE_RESET_IDLE_MS,
            lambda: self._set_dictation_state(DictationState.IDLE)
            if self._dictation_state in (DictationState.SUCCESS, DictationState.ERROR)
            else None,
        )

    @Slot(object)
    def _on_professional_result(self, cleaned_raw: object) -> None:
        """Handle the cleaned text from Professional Mode."""
        log.info("Professional result signal delivered to main thread")
        ctx = self._pro_context  # read BEFORE cancel clears it
        self._cancel_pro_timeout()
        if ctx is None:
            return  # already handled (e.g. by timeout)
        ts, original = ctx
        cleaned = str(cleaned_raw).strip()

        # Forward token stats to Developer Panel
        if self._dev_panel is not None and self._text_processor is not None:
            tps, ti, to, llm_seq = self._text_processor.token_stats
            self._dev_panel.realtime_widget.update_tokens(tps, ti, to, seq=llm_seq)

        if cleaned and cleaned != original:
            self._log_ui(f"Professional cleanup: {len(original)} -> {len(cleaned)} chars")
            self._add_history(ts, cleaned, success=True, original_text=original)
            output = cleaned
        else:
            self._log_ui("Professional cleanup returned unchanged text")
            self._add_history(ts, original, success=True)
            output = original

        copied = True
        if self._chk_auto_copy.isChecked():
            copied = set_clipboard_text(output)
            if copied:
                self._log_ui("Copied to clipboard")
            else:
                self._log_ui("Failed to copy to clipboard", error=True)

        if copied and self._chk_auto_paste.isChecked():
            def _paste():
                simulate_paste(wait_for_modifiers=self._chk_hotkeys.isChecked())
            w = Worker(_paste)
            self._pool.start(w)

        QTimer.singleShot(
            STATE_RESET_IDLE_MS,
            lambda: self._set_dictation_state(DictationState.IDLE)
            if self._dictation_state in (DictationState.SUCCESS, DictationState.ERROR)
            else None,
        )

    @Slot(str)
    def _on_professional_error(self, err: str) -> None:
        """Professional Mode cleanup failed — fall back to raw text."""
        log.info("Professional error signal delivered to main thread")
        ctx = self._pro_context  # read BEFORE cancel clears it
        self._cancel_pro_timeout()
        if ctx is None:
            return  # already handled (e.g. by timeout)
        ts, original = ctx
        self._log_ui(f"Professional cleanup failed: {err}", error=True)
        self._add_history(ts, original, success=True)

        copied = True
        if self._chk_auto_copy.isChecked():
            copied = set_clipboard_text(original)
            if copied:
                self._log_ui("Copied original text to clipboard (cleanup failed)")
            else:
                self._log_ui("Failed to copy to clipboard", error=True)

        if copied and self._chk_auto_paste.isChecked():
            def _paste():
                simulate_paste(wait_for_modifiers=self._chk_hotkeys.isChecked())
            w = Worker(_paste)
            self._pool.start(w)

        QTimer.singleShot(
            STATE_RESET_IDLE_MS,
            lambda: self._set_dictation_state(DictationState.IDLE)
            if self._dictation_state in (DictationState.SUCCESS, DictationState.ERROR)
            else None,
        )

    @Slot()
    def _on_professional_finished(self) -> None:
        """Worker done — drop the reference (prevent leak)."""
        self._pro_worker = None
        self._update_global_status()

    def _cancel_pro_timeout(self) -> None:
        """Stop the safety timer and clear professional-mode context."""
        if self._pro_timeout is not None:
            self._pro_timeout.stop()
            self._pro_timeout.deleteLater()
            self._pro_timeout = None
        self._pro_context = None

    @Slot()
    def _on_professional_timeout(self) -> None:
        """Safety net — professional cleanup did not complete in time."""
        ctx = self._pro_context
        self._pro_timeout = None
        self._pro_context = None
        self._pro_worker = None
        self._update_global_status()
        if ctx is None:
            return  # result/error already handled normally
        ts, original = ctx
        log.warning("Professional cleanup timed out — falling back to original text")
        self._log_ui("Professional cleanup timed out — using original text", error=True)
        self._add_history(ts, original, success=True)

        copied = True
        if self._chk_auto_copy.isChecked():
            copied = set_clipboard_text(original)
            if copied:
                self._log_ui("Copied original text to clipboard")
            else:
                self._log_ui("Failed to copy to clipboard", error=True)

        if copied and self._chk_auto_paste.isChecked():
            def _paste():
                simulate_paste(wait_for_modifiers=self._chk_hotkeys.isChecked())
            w = Worker(_paste)
            self._pool.start(w)

        QTimer.singleShot(
            STATE_RESET_IDLE_MS,
            lambda: self._set_dictation_state(DictationState.IDLE)
            if self._dictation_state in (DictationState.SUCCESS, DictationState.ERROR)
            else None,
        )

    @Slot(str)
    def _on_transcription_error(self, err: str) -> None:
        self._res_monitor.start()
        self._resume_mic_stream_after_processing()
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._set_dictation_state(DictationState.ERROR)

        # Detect CUDA errors and trigger automatic model reload so the next
        # transcription attempt has a clean GPU context.
        is_cuda_error = any(s in err for s in (
            "CUDA error", "AcceleratorError", "cudaError",
        ))
        if is_cuda_error and self._engine is not None and self._engine.is_loaded:
            self._log_ui("CUDA error detected — reloading model to recover…", error=True)
            self._add_history(ts, "CUDA error — reloading model…", success=False)
            self._on_reload_model()
            return

        self._log_ui(f"Transcription error: {err}", error=True)
        self._add_history(ts, f"Error: {err}", success=False)
        QTimer.singleShot(
            STATE_RESET_ERROR_MS,
            lambda: self._set_dictation_state(DictationState.IDLE)
            if self._dictation_state in (DictationState.SUCCESS, DictationState.ERROR)
            else None,
        )

    # ═════════════════════════════════════════════════════════════════════════
    # HISTORY
    # ═════════════════════════════════════════════════════════════════════════

    def _add_history(
        self,
        timestamp: str,
        text: str,
        success: bool,
        original_text: Optional[str] = None,
    ) -> None:
        from .history_widget import _HistoryEntry

        if self._active_draft_entry is not None:
            draft = self._active_draft_entry
            self._active_draft_entry = None
            draft.mark_final(text, success=success, original_text=original_text)
            return

        if self._dev_panel is None:
            self._history_buffer.append((timestamp, text, success, original_text))
            return

        hw = self._dev_panel.history_widget
        entry = _HistoryEntry(
            timestamp, text, success, parent=hw.history_content,
            original_text=original_text,
        )
        count = hw.history_layout.count()
        hw.history_layout.insertWidget(max(0, count - 1), entry)

    # ═════════════════════════════════════════════════════════════════════════
    # CLEAR LOGS & HISTORY
    # ═════════════════════════════════════════════════════════════════════════

    @Slot()
    def _on_clear_history(self) -> None:
        """Clear the in-memory transcription history."""
        self._history_buffer.clear()
        if self._dev_panel is not None:
            layout = self._dev_panel.history_widget.history_layout
            while layout.count() > 1:
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        self._log_ui("History cleared")

    @Slot()
    def _on_clear_logs(self) -> None:
        """Clear the UI log panel and on-disk log files."""
        self._log_text.clear()
        if self._dev_panel is not None:
            self._dev_panel.logs_widget.log_text.clear()
        self._delete_log_files()
        self._log_ui("Logs cleared")

    @Slot()
    def _on_copy_logs(self) -> None:
        """Copy all visible log text to the clipboard."""
        if self._dev_panel is not None:
            text = self._dev_panel.logs_widget.log_text.toPlainText()
        else:
            text = self._log_text.toPlainText()
        if text:
            if set_clipboard_text(text):
                self._log_ui("Logs copied to clipboard")
            else:
                self._log_ui("Failed to copy logs to clipboard", error=True)
        else:
            self._log_ui("No log text to copy")

    def _delete_log_files(self) -> None:
        """Remove the rotating log files from disk."""
        log_dir = DEFAULT_LOG_DIR
        for pattern in ("speakeasy.log", "speakeasy.log.*"):
            for f in log_dir.glob(pattern):
                try:
                    f.unlink()
                except OSError:
                    pass

    def _suspend_mic_stream_for_processing(self) -> None:
        """Close the live input stream before model inference starts."""
        if self._mic_suspended_for_processing:
            return
        try:
            self._recorder.close_stream()
            self._mic_suspended_for_processing = True
            self._log_ui("Microphone stream suspended for transcription")
        except Exception as exc:
            self._log_ui(f"Microphone suspend failed: {exc}", error=True)

    def _resume_mic_stream_after_processing(self) -> None:
        """Re-open the live input stream after model inference finishes."""
        if not self._mic_suspended_for_processing:
            return
        try:
            self._recorder.open_stream()
            self._log_ui("Microphone stream resumed")
        except Exception as exc:
            self._log_ui(f"Microphone resume failed: {exc}", error=True)
        finally:
            self._mic_suspended_for_processing = False

        # Delayed health check — verify the stream is actually delivering audio
        def _verify_stream():
            if not self._recorder.stream_is_alive():
                self._log_ui("Microphone stream stale after resume — recovering…")
                if self._recorder.recover_stream():
                    self._log_ui("Microphone stream recovered after resume")
                else:
                    self._log_ui(
                        "Microphone recovery failed — try changing the "
                        "audio device in Settings",
                        error=True,
                    )

        QTimer.singleShot(500, _verify_stream)

    # ═════════════════════════════════════════════════════════════════════════
    # SETTINGS
    # ═════════════════════════════════════════════════════════════════════════

    @Slot()
    def _on_open_settings(self) -> None:
        """Open the Developer Panel on the Settings tab."""
        from .developer_panel import TAB_SETTINGS

        if self._dev_panel is None:
            self._on_toggle_dev_panel()
        if self._dev_panel is not None:
            self._dev_panel.show_snapped()
            self._dev_panel.activate_tab(TAB_SETTINGS)

    def _ensure_dev_panel(self) -> None:
        """Create the Developer Panel if it doesn't exist yet (without showing it)."""
        from .developer_panel import DeveloperPanel

        if self._dev_panel is None:
            self._dev_panel = DeveloperPanel(self.settings, self)
            self._dev_panel.closed.connect(self._on_dev_panel_closed)
            self._flush_log_buffer()
            self._flush_history_buffer()
            self._set_model_status(self._model_status)

    def _on_toggle_dev_panel(self) -> None:
        """Show or hide the Developer Panel; create it lazily."""
        self._ensure_dev_panel()
        if self._dev_panel.isVisible():
            self._dev_panel.hide()
            self._btn_dev_panel.setChecked(False)
            self.settings.dev_panel_open = False
        else:
            self._dev_panel.show_snapped()
            self._btn_dev_panel.setChecked(True)
            self.settings.dev_panel_open = True
        self.settings.save()

    def _on_show_history(self) -> None:
        """Open the Developer Panel to the History tab."""
        from .developer_panel import TAB_HISTORY

        self._ensure_dev_panel()
        if not self._dev_panel.isVisible():
            self._dev_panel.show_snapped()
            self._btn_dev_panel.setChecked(True)
            self.settings.dev_panel_open = True
            self.settings.save()
        self._dev_panel.activate_tab(TAB_HISTORY)

    def _flush_history_buffer(self) -> None:
        """Replay buffered history entries into the Developer Panel's History tab."""
        from .history_widget import _HistoryEntry

        if not self._history_buffer or self._dev_panel is None:
            return
        hw = self._dev_panel.history_widget
        for timestamp, text, success, original_text in self._history_buffer:
            entry = _HistoryEntry(
                timestamp, text, success, parent=hw.history_content,
                original_text=original_text,
            )
            count = hw.history_layout.count()
            hw.history_layout.insertWidget(max(0, count - 1), entry)
        self._history_buffer.clear()

    def _on_dev_panel_closed(self) -> None:
        self._btn_dev_panel.setChecked(False)
        self.settings.dev_panel_open = False
        self.settings.save()

    # ── Granite model setup helpers ───────────────────────────────────────────

    def _prompt_model_setup_on_start(self) -> None:
        """Show the Granite setup dialog at startup when model is missing."""
        if self._prompt_granite_setup():
            # User ran setup successfully — try loading
            if self._granite_model_ready():
                self._load_model()
            else:
                self._log_ui("Model still not found after setup", error=True)
        else:
            self._log_ui(
                "Model setup declined — use Settings to configure later",
                error=True,
            )

    def _granite_model_ready(self) -> bool:
        """Return True if Granite model files are present locally."""
        from .model_downloader import model_ready
        return model_ready("granite", self.settings.model_path)

    def _prompt_granite_setup(self) -> bool:
        """Show a dialog explaining Granite model download requirements.

        If the user chooses to proceed, launch ``granite-model-setup.ps1``
        and return True if the model was successfully downloaded.
        If the user declines, return False.
        """
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("IBM Granite Speech — Setup Required")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(
            "The IBM Granite Speech model must be downloaded from HuggingFace "
            "before local transcription can run."
        )
        msg.setInformativeText(
            "<b>Setup steps:</b><br><br>"
            "1. Create a free account at:<br>"
            '&nbsp;&nbsp;&nbsp;<a href="https://huggingface.co/join">'
            "https://huggingface.co/join</a><br><br>"
            "2. Visit the model page:<br>"
            '&nbsp;&nbsp;&nbsp;<a href="https://huggingface.co/ibm-granite/granite-speech-4.1-2b">'
            "https://huggingface.co/ibm-granite/granite-speech-4.1-2b</a><br><br>"
            "3. Create an access token if HuggingFace requests one:<br>"
            '&nbsp;&nbsp;&nbsp;<a href="https://huggingface.co/settings/tokens">'
            "https://huggingface.co/settings/tokens</a><br><br>"
            "Would you like to run the Granite model setup now?"
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.Yes)

        if msg.exec() != QMessageBox.StandardButton.Yes:
            return False

        # In source (non-frozen) mode, download directly — no elevation needed
        # since dev-temp/ is user-writable and speakeasy.exe doesn't exist.
        if not getattr(sys, "frozen", False):
            return self._run_source_model_download()

        # Launch granite-model-setup.ps1 (frozen/installed builds)
        return self._run_granite_setup_script()

    def _run_source_model_download(self) -> bool:
        """Collect a HuggingFace token via dialog and download directly."""
        from PySide6.QtWidgets import QInputDialog, QLineEdit

        token, ok = QInputDialog.getText(
            self,
            "HuggingFace Token",
            "Paste your HuggingFace access token\n"
            "(Read permission, from https://huggingface.co/settings/tokens):",
            QLineEdit.EchoMode.Password,
        )
        if not ok or not token.strip():
            self._log_ui("Model download cancelled — no token provided", error=True)
            return False

        self._log_ui("Downloading Granite model (this may take several minutes)…")
        # Force a repaint so the log message is visible before the blocking call
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        from .model_downloader import download_model, EXIT_SUCCESS, EXIT_AUTH_REQUIRED

        rc = download_model("granite", self.settings.model_path, token=token.strip())
        if rc == EXIT_SUCCESS:
            self._log_ui("Granite model downloaded successfully")
            return True
        elif rc == EXIT_AUTH_REQUIRED:
            QMessageBox.warning(
                self,
                "Authentication Failed",
                "The token was rejected. Possible causes:\n\n"
                "• Invalid or expired token\n"
                "• HuggingFace denied access to:\n"
                "  https://huggingface.co/ibm-granite/granite-speech-4.1-2b\n\n"
                "Please verify your token and repo access, then try again.",
            )
            return False
        else:
            QMessageBox.warning(
                self,
                "Download Failed",
                "The model download failed. Check the log for details.\n\n"
                "You can retry from Settings or run:\n"
                "  uv run python -m speakeasy download-model --token <TOKEN>",
            )
            return False

    def _run_granite_setup_script(self) -> bool:
        """Launch ``granite-model-setup.ps1`` and return True if the model
        is present afterwards."""
        from .model_downloader import (
            get_granite_setup_script_candidates,
            launch_granite_setup_script,
        )

        install_script, repo_script = get_granite_setup_script_candidates()
        if install_script == repo_script:
            searched_paths = f"  {install_script}"
        else:
            searched_paths = f"  {install_script}\n  {repo_script}"

        model_dir = Path(self.settings.model_path) / "granite"

        self._log_ui("Launching Granite model setup…")
        try:
            ret = launch_granite_setup_script(target_dir=self.settings.model_path)
        except FileNotFoundError:
            QMessageBox.critical(
                self,
                "Setup Script Missing",
                f"Could not find granite-model-setup.ps1 in:\n"
                f"{searched_paths}\n\n"
                "Please reinstall SpeakEasy AI Granite or run the Granite setup manually.",
            )
            return False
        except Exception as exc:
            self._log_ui(f"Failed to launch Granite setup: {exc}", error=True)
            return False

        if ret <= 32:
            self._log_ui("Granite setup was cancelled or failed to launch", error=True)
            return False

        confirm = QMessageBox.question(
            self,
            "Granite Setup",
            "The Granite model setup wizard has been launched in a\n"
            "separate window. Click OK once it has finished.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )
        if confirm == QMessageBox.StandardButton.Cancel:
            return False

        # Check if the model was actually downloaded
        if self._granite_model_ready():
            self._log_ui("Granite model is ready")
            return True
        else:
            QMessageBox.warning(
                self,
                "Granite Model Not Found",
                "The Granite model was not detected after setup.\n\n"
                f"Expected model directory:\n  {model_dir}\n\n"
                "You can try again later from Settings, or run\n"
                "granite-model-setup.ps1 from the install directory.",
            )
            return False

    def _apply_settings(self) -> None:
        """Re-apply changed settings to live components."""
        s = self.settings

        # Audio (need to re-open stream if device changed)
        new_dev = s.mic_device_index if s.mic_device_index >= 0 else None
        if new_dev != self._recorder.device:
            self._recorder.close_stream()
            self._recorder.device = new_dev
            try:
                self._recorder.open_stream()
                self._log_ui("Microphone stream re-opened")
            except Exception as exc:
                self._log_ui(f"Microphone error: {exc}", error=True)
        self._recorder.sample_rate = s.sample_rate
        self._recorder.silence_threshold = s.silence_threshold
        self._recorder.silence_margin = int(s.sample_rate * s.silence_margin_ms / 1000)

        # Hotkeys
        if s.hotkeys_enabled:
            self._hotkey_mgr.register(
                s.hotkey_start, s.hotkey_quit, hwnd=int(self.winId()),
                hotkey_dev_panel=s.hotkey_dev_panel,
            )
        else:
            self._hotkey_mgr.unregister()
        self._chk_hotkeys.setChecked(s.hotkeys_enabled)
        self._chk_auto_copy.setChecked(s.auto_copy)
        self._chk_auto_paste.setChecked(s.auto_paste)

        # Professional Mode
        if s.device != "cuda":
            self._device_fallback_to_cpu = False
        self._active_preset = self._pro_presets.get(s.pro_active_preset)
        if s.professional_mode and self._api_key and self._active_preset:
            model = self._active_preset.model or "gpt-5.4-mini"
            self._text_processor = TextProcessor(
                api_key=self._api_key, model=model,
            )
            self._log_ui("Professional Mode enabled")
        else:
            self._text_processor = None
            if s.professional_mode and not self._api_key:
                self._log_ui(
                    "Professional Mode enabled but no API key configured",
                    error=True,
                )

        self._log_ui("Settings applied")
        self._update_global_status()

    @Slot()
    def _on_open_pro_settings(self) -> None:
        """Open the Developer Panel on the Pro Mode tab."""
        from .developer_panel import TAB_PRO

        if self._dev_panel is None:
            self._on_toggle_dev_panel()
        if self._dev_panel is not None:
            self._dev_panel.show_snapped()
            self._dev_panel.activate_tab(TAB_PRO)

    def _on_pro_mode_applied(self) -> None:
        """Handle settings_applied from the ProModeWidget in the Developer Panel."""
        if self._dev_panel is not None:
            pw = self._dev_panel.pro_mode_widget
            self._api_key = pw.api_key
            self._pro_presets = pw.presets
            self._active_preset = self._pro_presets.get(
                self.settings.pro_active_preset,
            )

        # Re-create or destroy TextProcessor based on new state
        if self.settings.professional_mode and self._api_key and self._active_preset:
            model = self._active_preset.model or "gpt-5.4-mini"
            self._text_processor = TextProcessor(
                api_key=self._api_key, model=model,
            )
            self._log_ui("Professional Mode enabled")
        else:
            self._text_processor = None
            if self.settings.professional_mode and not self._api_key:
                self._log_ui(
                    "Professional Mode enabled but no API key configured",
                    error=True,
                )

        self._chk_professional.blockSignals(True)
        self._chk_professional.setChecked(self.settings.professional_mode)
        self._chk_professional.blockSignals(False)
        self._combo_pro_preset.setEnabled(self.settings.professional_mode)
        self._populate_pro_preset_combo()
        self._update_global_status()

    def _populate_pro_preset_combo(self) -> None:
        """Populate the preset quick-select combo from the current presets dict."""
        self._combo_pro_preset.blockSignals(True)
        self._combo_pro_preset.clear()
        for name in sorted(self._pro_presets.keys()):
            self._combo_pro_preset.addItem(name)
        idx = self._combo_pro_preset.findText(self.settings.pro_active_preset)
        if idx >= 0:
            self._combo_pro_preset.setCurrentIndex(idx)
        self._combo_pro_preset.blockSignals(False)

    @Slot(str)
    def _on_pro_preset_quick_select(self, name: str) -> None:
        """Handle preset selection from the quick-select combo."""
        if not name or name == self.settings.pro_active_preset:
            return
        preset = self._pro_presets.get(name)
        if preset is None:
            return
        self.settings.pro_active_preset = name
        self._active_preset = preset
        if self.settings.professional_mode and self._api_key and self._text_processor is not None:
            model = preset.model or "gpt-5.4-mini"
            self._text_processor = TextProcessor(api_key=self._api_key, model=model)
            self._log_ui(f'Pro preset changed to "{name}"')
        self.settings.save()
        self._update_global_status()

    def _on_professional_toggled(self, checked: bool) -> None:
        """Handle the Professional Mode checkbox in the main toggle row."""
        if checked:
            if not self._api_key:
                self._chk_professional.blockSignals(True)
                self._chk_professional.setChecked(False)
                self._chk_professional.blockSignals(False)
                reply = QMessageBox.question(
                    self,
                    "API Key Required",
                    "Professional Mode requires an OpenAI API key.\n\n"
                    "Would you like to open Professional Mode Settings "
                    "to configure one?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._on_open_pro_settings()
                self._update_global_status()
                return
            if self._active_preset is None:
                self._chk_professional.blockSignals(True)
                self._chk_professional.setChecked(False)
                self._chk_professional.blockSignals(False)
                reply = QMessageBox.question(
                    self,
                    "No Preset Configured",
                    "Professional Mode requires an active preset.\n\n"
                    "Would you like to open Professional Mode Settings "
                    "to configure one?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._on_open_pro_settings()
                self._update_global_status()
                return
            # All prerequisites met — show one-time data-privacy disclosure
            if not self.settings.pro_disclosure_accepted:
                disc = QMessageBox(self)
                disc.setIcon(QMessageBox.Icon.Warning)
                disc.setWindowTitle("Data Privacy Notice: Optional Professional Mode")
                disc.setText(
                    "All transcription is local to this machine and is not stored, "
                    "externally transmitted, or logged."
                )
                disc.setInformativeText(
                    "If you choose to enable Professional Mode, dictation results will "
                    "be transmitted to <b>api.openai.com</b> under your personal "
                    "OpenAI API key.<br><br>"
                    "&#x26a0;&#xfe0f;&nbsp; Do not dictate confidential content, "
                    "including personal data (PII/PHI), financial records, "
                    "proprietary business information, or content that identifies "
                    "colleagues or customers.<br><br>"
                    "By clicking <b>I Understand</b> you acknowledge this notice. "
                    "It will not be shown again."
                )
                disc.setStandardButtons(
                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
                )
                disc.setDefaultButton(QMessageBox.StandardButton.Cancel)
                disc.button(QMessageBox.StandardButton.Ok).setText("I Understand")
                if disc.exec() != QMessageBox.StandardButton.Ok:
                    self._chk_professional.blockSignals(True)
                    self._chk_professional.setChecked(False)
                    self._chk_professional.blockSignals(False)
                    self._update_global_status()
                    return
                self.settings.pro_disclosure_accepted = True
            # All prerequisites met — enable
            self.settings.professional_mode = True
            model = self._active_preset.model or "gpt-5.4-mini"
            self._text_processor = TextProcessor(
                api_key=self._api_key, model=model,
            )
            self._log_ui("Professional Mode enabled")
        else:
            self.settings.professional_mode = False
            self._text_processor = None
            self._log_ui("Professional Mode disabled")
        self._combo_pro_preset.setEnabled(self.settings.professional_mode)
        self.settings.save()
        self._update_global_status()

    # ═════════════════════════════════════════════════════════════════════════
    # SLEEP / WAKE RECOVERY
    # ═════════════════════════════════════════════════════════════════════════

    def nativeEvent(self, event_type, message):
        """Intercept Windows power-management broadcasts."""
        if event_type == b"windows_generic_MSG":
            try:
                import ctypes.wintypes

                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    self._hotkey_mgr.handle_wm_hotkey(int(msg.wParam))
                    return True, 0
                if msg.message == WM_POWERBROADCAST and msg.wParam in (
                    PBT_APMRESUMEAUTOMATIC,
                    PBT_APMRESUMESUSPEND,
                ):
                    now = time.time()
                    if now - self._last_resume_time > SYSTEM_RESUME_DEBOUNCE_S:
                        self._last_resume_time = now
                        QTimer.singleShot(SYSTEM_RESUME_DELAY_MS, self._on_system_resume)
            except Exception:
                log.debug("nativeEvent parsing failed", exc_info=True)
        return super().nativeEvent(event_type, message)

    def _on_system_resume(self) -> None:
        """Re-register hotkeys and re-open the mic stream after sleep/wake."""
        log.info("System resume from sleep detected")
        self._log_ui("System resume detected — re-registering hotkeys")

        if self._chk_hotkeys.isChecked():
            self._hotkey_mgr.re_register()

        try:
            self._recorder.close_stream()
            self._recorder.open_stream()
            self._log_ui("Microphone stream re-opened after resume")
        except Exception as exc:
            self._log_ui(f"Microphone error after resume: {exc}", error=True)

        # Proactive CUDA health check: after sleep/wake the GPU context can
        # be silently corrupted, causing "CUDA error: unknown error" on the
        # next transcription.  A small allocation test catches this early and
        # triggers a model reload before the user hits the error.
        if (
            self._engine is not None
            and self._engine.is_loaded
            and self._actual_engine_device() == "cuda"
        ):
            try:
                import torch
                _probe = torch.zeros(1, device="cuda")
                del _probe
            except Exception:
                log.warning("CUDA health check failed after resume — reloading model")
                self._log_ui("CUDA context lost after sleep — reloading model…", error=True)
                self._on_reload_model()

    # ═════════════════════════════════════════════════════════════════════════
    # CLEANUP
    # ═════════════════════════════════════════════════════════════════════════

    def moveEvent(self, event):
        super().moveEvent(event)
        if self._dev_panel and self._dev_panel.isVisible():
            self._dev_panel.on_main_window_moved()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._dev_panel and self._dev_panel.isVisible():
            self._dev_panel.on_main_window_moved()

    def closeEvent(self, event) -> None:
        """Graceful shutdown."""
        self._log_ui("Shutting down…")
        self._loading_timer.stop()
        self._res_monitor.stop()
        self._hotkey_mgr.unregister()
        self._recorder.close_stream()
        engine_tasks_done = self._engine_pool.waitForDone(5000)
        self._engine_pool.shutdown(wait=False, cancel_futures=False)
        if engine_tasks_done:
            self._engine.unload()
        else:
            log.warning("Skipping engine unload during shutdown because an engine task is still running")
        # Wait for any in-flight thread-pool workers (transcription, model
        # load, metrics poll) to finish so the process can exit cleanly.
        self._pool.waitForDone(5000)
        if self.settings.clear_logs_on_exit:
            self._delete_log_files()
        event.accept()
        # Explicitly quit the application so that any open modal dialogs
        # (e.g. Settings) don't keep the process alive.
        QApplication.instance().quit()
