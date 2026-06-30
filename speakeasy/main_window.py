"""
Main application window for SpeakEasy AI.

Integrates model engine lifecycle, audio recording, transcription,
clipboard, hotkeys, and history into a single cohesive window.
"""

from __future__ import annotations

import datetime
import logging
import time
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRect, QThreadPool, QTimer, Qt, Property, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen
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

from .audio import AudioRecorder, play_beep
from .app_identity import app_icon_path
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
from .core.contract import TranscriptionOptions, TranscriptionService
from .services.inprocess import InProcessEngineService
from .hotkeys import HotkeyManager
from ._resource_monitor import ResourceMonitor
from .pro_preset import ProPreset, bootstrap_presets, load_all_presets
from .pro_mode_widget import PROFILE_NONE
from .status_pills import ProMode, StatusPillBar
from .text_processor import TextProcessor, load_api_key_from_keyring
from .ui.metrics_bridge import MetricsBridge
from .ui.model_controller import ModelController
from .ui.dictation_controller import DictationController
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

    def setChecked(self, checked: bool) -> None:
        previous = self.isChecked()
        super().setChecked(checked)
        if not hasattr(self, "_anim"):
            return
        if self.signalsBlocked() or previous == self.isChecked():
            self._anim.stop()
            self._knob_pos = 1.0 if self.isChecked() else 0.0
            self.update()

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
        self._raising_window_group = False
        self._pool = QThreadPool.globalInstance()
        self._engine_pool = engine_pool if engine_pool is not None else DedicatedWorkerPool(self)
        self._engine_pool.setMaxThreadCount(1)
        self._engine_pool.setExpiryTimeout(-1)

        # ── Controllers ──────────────────────────────────────────────────────
        # Plain-QObject controllers (plan §9) that hold a back-reference to this
        # window and own the model lifecycle and dictation state machine.
        self._model_controller = ModelController(self)
        self._dictation_controller = DictationController(self)

        # ── Engine ───────────────────────────────────────────────────────────
        # MainWindow talks only to a TranscriptionService.  A caller may inject
        # either a ready-made service or a raw duck-typed engine (tests do the
        # latter); wrap the latter in the in-process adapter.  With no injection
        # we build the in-process service for the configured engine — the heavy
        # torch/transformers import is deferred to model-load time.
        if engine is not None:
            self._service: TranscriptionService = (
                engine
                if isinstance(engine, InProcessEngineService)
                else InProcessEngineService(engine)
            )
        else:
            self._service = self._model_controller._build_service_from_settings()

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
        # Buffer for history entries added before the Developer Panel exists.
        self._history_buffer: list[tuple] = []

        # ── Resource monitor ─────────────────────────────────────────────────
        self._res_monitor = ResourceMonitor(
            pool=self._pool, interval_ms=METRICS_POLL_MS, parent=self,
        )
        self._metrics_bridge = MetricsBridge(self)
        self._res_monitor.metrics_updated.connect(self._metrics_bridge.on_metrics_result)
        self._res_monitor.metrics_error.connect(
            lambda err: log.error("Metrics poll error: %s", err)
        )

        # ── AI Writing Profiles ──────────────────────────────────────────────
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
                model=settings.pro_default_model,
            )
        elif settings.professional_mode and not self._api_key:
            log.warning("AI Writing Profiles enabled but no API key configured")

        # ── Build UI ─────────────────────────────────────────────────────────
        self.setWindowTitle("SpeakEasy AI Granite — Voice to Text")
        _icon_path = app_icon_path()
        if _icon_path.is_file():
            self.setWindowIcon(QIcon(str(_icon_path)))
        self.setMinimumWidth(400)
        self.resize(475, 465)
        self._build_ui()
        self._apply_content_height_resize()
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
        if self._model_controller._granite_model_ready():
            self._model_controller._load_model()
        else:
            health_summary = self._model_controller._granite_model_health_summary()
            log.warning("Granite model is not ready: %s", health_summary)
            self._model_controller._set_model_status(ModelStatus.ERROR)
            self._log_ui("Model incomplete or missing — setup required", error=True)
            # Defer dialog to after the event loop starts so the window is visible
            QTimer.singleShot(500, self._model_controller._prompt_model_setup_on_start)

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
        self._btn_record.clicked.connect(self._dictation_controller._on_toggle_recording)

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
        title_font = QFont(Font.FAMILY, 16)
        title_font.setWeight(QFont.Weight.DemiBold)
        self._record_title.setFont(title_font)
        self._record_title.setStyleSheet(f"color: {Color.TEXT_PRIMARY}; background: transparent; font-weight: 700; font-size: 16pt;")
        title_height = QFontMetrics(title_font).height()
        self._record_title.setFixedHeight(title_height)
        self._record_dot = QLabel("●")
        status_font = QFont(Font.FAMILY, 13)
        status_font.setWeight(QFont.Weight.DemiBold)
        self._record_dot.setFont(status_font)
        self._record_dot.setFixedHeight(title_height)
        self._record_dot.setStyleSheet(f"color: {Color.SUCCESS}; background: transparent; font-weight: 700;")
        self._record_status = QLabel("Ready")
        self._record_status.setFont(status_font)
        self._record_status.setFixedHeight(title_height)
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
        self._btn_dev_panel.setIconSize(QSize(20, 20))
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

        # ── Status indicators (model + dictation + writing profile) ─────────
        self._status_bar = StatusPillBar(self)
        self._status_bar.ai_model_clicked.connect(self._on_open_settings)
        self._status_bar.pro_mode_clicked.connect(self._on_open_pro_settings)
        root.addWidget(self._status_bar)
        self._update_global_status()
        self._dictation_controller._refresh_dictation_buttons()

        # ── Transcription Mode ───────────────────────────────────────────────
        transcription_section, transcription_layout = make_section_panel(
            "Transcription Mode", central, icon_name="sparkles", collapsible=True, expanded=False,
        )
        self._transcription_section_toggle = getattr(transcription_section, "_section_toggle")
        self._transcription_section_content = getattr(transcription_section, "_section_content")
        self._transcription_section_toggle.toggled.connect(self._resize_to_content_height)
        self._chk_transcription_mode = ToggleSwitch()
        self._chk_transcription_mode.setChecked(self.settings.professional_mode)
        self._chk_transcription_mode.toggled.connect(self._on_transcription_mode_toggled)
        transcription_layout.addWidget(make_setting_row(
            "Enabled", self._chk_transcription_mode, transcription_section,
        ))

        profile_row_widget = QWidget(transcription_section)
        profile_row = QHBoxLayout(profile_row_widget)
        profile_row.setContentsMargins(0, 0, 0, 0)
        profile_row.setSpacing(Spacing.SM)
        profile_label = QLabel("Profile")
        profile_label.setStyleSheet(f"color: {Color.TEXT_HEADING};")
        self._combo_pro_preset = QComboBox()
        self._combo_pro_preset.setMinimumWidth(260)
        self._combo_pro_preset.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._combo_pro_preset.setToolTip("Select the profile used when Transcription Mode is enabled.")
        self._combo_pro_preset.currentTextChanged.connect(self._on_main_profile_selected)
        self._refresh_main_profile_combo()
        profile_row.addWidget(profile_label, 0, Qt.AlignmentFlag.AlignVCenter)
        profile_row.addWidget(self._combo_pro_preset, 1, Qt.AlignmentFlag.AlignVCenter)
        transcription_layout.addWidget(profile_row_widget)
        root.addWidget(transcription_section)

        # ── Automation ───────────────────────────────────────────────────────
        automation_section, automation_layout = make_section_panel(
            "Automation", central, icon_name="keyboard", collapsible=True, expanded=False,
        )
        self._automation_section_toggle = getattr(automation_section, "_section_toggle")
        self._automation_section_content = getattr(automation_section, "_section_content")
        self._automation_section_toggle.toggled.connect(self._resize_to_content_height)
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

    def _resize_to_content_height(self, *_args) -> None:
        """Resize the top-level window to the current visible main layout height."""
        self._apply_content_height_resize()
        QTimer.singleShot(0, self._apply_content_height_resize)

    def _apply_content_height_resize(self) -> None:
        central = self.centralWidget()
        if central is None:
            return

        layout = central.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
            self.setMinimumHeight(layout.minimumSize().height())

        target_height = max(self.minimumHeight(), self.sizeHint().height())
        if target_height > 0:
            self.resize(self.width(), target_height)

    def _update_global_status(self) -> None:
        """Refresh the unified status bar with model, dictation, and writing profile state."""
        if not hasattr(self, "_status_bar"):
            return

        engine_display = str(self._service.descriptor().name).capitalize()
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

    def _refresh_main_profile_combo(self) -> None:
        if not hasattr(self, "_combo_pro_preset"):
            return

        selected = (
            self.settings.pro_active_preset
            if self.settings.pro_active_preset in self._pro_presets
            else PROFILE_NONE
        )
        self._combo_pro_preset.blockSignals(True)
        self._combo_pro_preset.clear()
        self._combo_pro_preset.addItem(PROFILE_NONE)
        for name in sorted(self._pro_presets.keys()):
            self._combo_pro_preset.addItem(name)
        idx = self._combo_pro_preset.findText(selected)
        self._combo_pro_preset.setCurrentIndex(idx if idx >= 0 else 0)
        self._combo_pro_preset.blockSignals(False)

    def _sync_profile_controls_from_settings(self) -> None:
        if hasattr(self, "_chk_transcription_mode"):
            self._chk_transcription_mode.blockSignals(True)
            self._chk_transcription_mode.setChecked(self.settings.professional_mode)
            self._chk_transcription_mode.blockSignals(False)
        self._refresh_main_profile_combo()
        if self._dev_panel is not None:
            self._dev_panel.pro_mode_widget.sync_from_settings()
            ap = getattr(self._dev_panel, "ai_providers_widget", None)
            if ap is not None:
                ap.sync_from_settings()

    def _apply_profile_runtime_state(self) -> None:
        self._active_preset = self._pro_presets.get(self.settings.pro_active_preset)
        if self.settings.professional_mode and self._api_key and self._active_preset:
            self._text_processor = TextProcessor(
                api_key=self._api_key,
                model=self.settings.pro_default_model,
            )
            self._log_ui("AI Writing Profiles enabled")
        else:
            self._text_processor = None
            if self.settings.professional_mode and not self._api_key:
                self._log_ui(
                    "AI Writing Profiles enabled but no API key configured",
                    error=True,
                )

    @Slot(bool)
    def _on_transcription_mode_toggled(self, checked: bool) -> None:
        if not checked:
            self.settings.professional_mode = False
            self.settings.save()
            self._apply_profile_runtime_state()
            self._sync_profile_controls_from_settings()
            self._update_global_status()
            return

        selected = self._combo_pro_preset.currentText() if hasattr(self, "_combo_pro_preset") else ""
        preset = self._pro_presets.get(selected) or self._pro_presets.get(self.settings.pro_active_preset)
        if preset is None and self._pro_presets:
            preset = self._pro_presets[sorted(self._pro_presets.keys())[0]]

        if preset is None:
            self._sync_profile_controls_from_settings()
            return

        if not self.settings.pro_disclosure_accepted and not self._show_pro_disclosure():
            self._sync_profile_controls_from_settings()
            return

        self.settings.pro_active_preset = preset.name
        self.settings.professional_mode = True
        self.settings.save()
        self._apply_profile_runtime_state()
        self._sync_profile_controls_from_settings()
        self._update_global_status()
        if not self._api_key:
            self._prompt_for_missing_api_key()

    @Slot(str)
    def _on_main_profile_selected(self, text: str) -> None:
        if not text:
            return

        if text == PROFILE_NONE:
            self.settings.pro_active_preset = ""
            self.settings.professional_mode = False
            self.settings.save()
            self._apply_profile_runtime_state()
            self._sync_profile_controls_from_settings()
            self._update_global_status()
            return

        preset = self._pro_presets.get(text)
        if preset is None:
            self._refresh_main_profile_combo()
            return

        if not self.settings.professional_mode:
            self.settings.pro_active_preset = preset.name
            self.settings.save()
            self._sync_profile_controls_from_settings()
            self._update_global_status()
            return

        if not self.settings.pro_disclosure_accepted and not self._show_pro_disclosure():
            self._refresh_main_profile_combo()
            return

        self.settings.pro_active_preset = preset.name
        self.settings.professional_mode = True
        self.settings.save()
        self._apply_profile_runtime_state()
        self._sync_profile_controls_from_settings()
        self._update_global_status()
        if not self._api_key:
            self._prompt_for_missing_api_key()

    def _show_pro_disclosure(self) -> bool:
        disc = QMessageBox(self)
        disc.setIcon(QMessageBox.Icon.Warning)
        disc.setWindowTitle("Data Privacy Notice: Optional AI Writing Profiles")
        disc.setText(
            "All transcription is local to this machine and is not stored, "
            "externally transmitted, or logged."
        )
        disc.setInformativeText(
            "If you choose to use <b>AI Writing Profiles</b>, dictation results will "
            "be transmitted to <b>api.openai.com</b> under your specified "
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
        if disc.exec() == QMessageBox.StandardButton.Ok:
            self.settings.pro_disclosure_accepted = True
            self.settings.save()
            return True
        return False

    def _prompt_for_missing_api_key(self) -> None:
        QMessageBox.information(
            self,
            "OpenAI API Key Required",
            "AI Writing Profiles need an OpenAI API key before rewriting can run. "
            "Enter your key in AI Providers to finish setup.",
        )
        self._on_open_ai_providers()

    @Slot()
    def _on_open_ai_providers(self) -> None:
        """Open the Developer Panel on the AI Writing Profiles tab (AI Providers
        is folded in there since Phase 6) and focus the API-key field."""
        from .developer_panel import TAB_PRO

        if self._dev_panel is None:
            self._on_toggle_dev_panel()
        if self._dev_panel is not None:
            self._dev_panel.show_snapped()
            self._dev_panel.activate_tab(TAB_PRO)
            ap = getattr(self._dev_panel, "ai_providers_widget", None)
            if ap is not None:
                ap.focus_api_key()

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
        self._loading_timer.timeout.connect(self._model_controller._update_loading_label)
        self._loading_timer.setInterval(LOADING_TICK_MS)

        # Start resource-metrics polling
        self._res_monitor.start()

    # ═════════════════════════════════════════════════════════════════════════
    # HOTKEYS
    # ═════════════════════════════════════════════════════════════════════════

    def _connect_hotkeys(self) -> None:
        self._hotkey_mgr.toggle_requested.connect(self._dictation_controller._on_toggle_recording)
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

    # ── Model lifecycle ───────────────────────────────────────────────────────
    # Moved to speakeasy.ui.model_controller.ModelController (plan §9, Phase 6).

    # ── Resource metrics ──────────────────────────────────────────────────────

    # —— Validate ——————————————————————————————————————————————————————————————

    @Slot()
    def _on_validate(self) -> None:
        if not self._service.is_loaded:
            self._log_ui("Cannot validate — model not loaded", error=True)
            return
        self._model_controller._set_model_status(ModelStatus.VALIDATING)
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
            audio_16k = self._model_controller._resample_to_16k(audio, sr)
            text = self._service.transcribe(audio_16k, TranscriptionOptions()).text
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
            self._model_controller._set_model_status(ModelStatus.VALIDATED)
            self._log_ui(f"Validation passed: {msg}")
        else:
            self._model_controller._set_model_status(ModelStatus.ERROR)
            self._log_ui(f"Validation failed: {msg}", error=True)

    # ═════════════════════════════════════════════════════════════════════════
    # DICTATION
    # ═════════════════════════════════════════════════════════════════════════
    # The record → transcribe → paste state machine moved to
    # speakeasy.ui.dictation_controller.DictationController (plan §9, Phase 6).

    # ═════════════════════════════════════════════════════════════════════════
    # HISTORY
    # ═════════════════════════════════════════════════════════════════════════
    # _add_history moved to DictationController (plan §9, Phase 6).

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
                widget = item.widget() if item is not None else None
                if widget is not None:
                    widget.deleteLater()
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

    # _suspend_mic_stream_for_processing / _resume_mic_stream_after_processing
    # moved to DictationController (plan §9, Phase 6).

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
            self._model_controller._set_model_status(self._model_status)

    def _on_toggle_dev_panel(self) -> None:
        """Show or hide the Developer Panel; create it lazily."""
        self._ensure_dev_panel()
        panel = self._dev_panel
        if panel is None:
            return
        if panel.isVisible():
            panel.hide()
            self._btn_dev_panel.setChecked(False)
            self.settings.dev_panel_open = False
        else:
            panel.show_snapped()
            self._btn_dev_panel.setChecked(True)
            self.settings.dev_panel_open = True
        self.settings.save()

    def _on_show_history(self) -> None:
        """Open the Developer Panel to the History tab."""
        from .developer_panel import TAB_HISTORY

        self._ensure_dev_panel()
        panel = self._dev_panel
        if panel is None:
            return
        if not panel.isVisible():
            panel.show_snapped()
            self._btn_dev_panel.setChecked(True)
            self.settings.dev_panel_open = True
            self.settings.save()
        panel.activate_tab(TAB_HISTORY)

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
    # Moved to speakeasy.ui.model_controller.ModelController (plan §9, Phase 6).

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

        # AI Writing Profiles
        if s.device != "cuda":
            self._device_fallback_to_cpu = False
        self._apply_profile_runtime_state()
        self._sync_profile_controls_from_settings()

        self._log_ui("Settings applied")
        self._update_global_status()

    @Slot()
    def _on_open_pro_settings(self) -> None:
        """Open the Developer Panel on the AI Writing Profiles tab."""
        from .developer_panel import TAB_PRO

        if self._dev_panel is None:
            self._on_toggle_dev_panel()
        if self._dev_panel is not None:
            self._dev_panel.show_snapped()
            self._dev_panel.activate_tab(TAB_PRO)

    def _on_pro_mode_applied(self) -> None:
        """Handle settings_applied from the AI Writing Profiles or AI Providers tab.

        Re-syncs internal state (api key, presets, active preset, text
        processor) and refreshes the status pill.  The main window exposes
        an explicit on/off toggle while the profile selector chooses which
        rewrite profile to use when enabled.
        """
        if self._dev_panel is not None:
            pw = self._dev_panel.pro_mode_widget
            self._pro_presets = pw.presets
            self._active_preset = self._pro_presets.get(self.settings.pro_active_preset)
            ap = getattr(self._dev_panel, "ai_providers_widget", None)
            if ap is not None:
                self._api_key = ap.api_key

        self._apply_profile_runtime_state()

        self._sync_profile_controls_from_settings()
        self._update_global_status()

    @Slot(str)
    def _on_api_key_changed(self, key: str) -> None:
        """API key updated in the AI Providers tab."""
        self._api_key = key or ""
        if self.settings.professional_mode and self._api_key and self._active_preset:
            self._text_processor = TextProcessor(
                api_key=self._api_key, model=self.settings.pro_default_model,
            )
        else:
            self._text_processor = None
        self._sync_profile_controls_from_settings()
        self._update_global_status()

    def _sync_pro_mode_widget_from_settings(self) -> None:
        self._sync_profile_controls_from_settings()

    def _populate_pro_preset_combo(self) -> None:
        """Refresh the in-memory presets dict and the Pro Mode widget combo.

        The main window selector and developer-panel ProModeWidget both use
        the shared settings object; this hook keeps their option lists aligned
        after preset CRUD changes.
        """
        self._pro_presets = load_all_presets(DEFAULT_PRESETS_DIR)
        self._refresh_main_profile_combo()
        if self._dev_panel is not None:
            self._dev_panel.pro_mode_widget.sync_from_settings()
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

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.WindowActivate and hasattr(self, "_raising_window_group"):
            self._raise_window_group(preferred="main")
        return super().event(event)

    def _raise_window_group(self, preferred: str = "main") -> None:
        if self._raising_window_group:
            return

        self._raising_window_group = True
        try:
            panel = self._dev_panel

            if preferred == "panel" and panel is not None and panel.isVisible():
                self.raise_()
                panel.raise_()
                panel.activateWindow()
                return

            self.raise_()
            self.activateWindow()
            if panel is not None and panel.isVisible():
                panel.raise_()
        finally:
            self._raising_window_group = False

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

        # Proactive model reload after sleep/wake on CUDA.  Sleep (S3) and
        # hibernate (S4) do not preserve VRAM, so the multi-GB model weights
        # loaded into GPU memory are stale/garbage after resume even when the
        # CUDA *context* recovers.  A tiny allocation probe only confirms the
        # context can allocate — it cannot detect corrupted weights — and the
        # model then keeps "working" while silently producing degraded output
        # (the first thing to break is punctuation/capitalization).  Because
        # VRAM weights can never be trusted after a resume, unconditionally
        # reload the model rather than relying on the allocation probe.
        if self._service.is_loaded and self._model_controller._actual_engine_device() == "cuda":
            log.warning("Resume on CUDA — VRAM weights cannot be trusted; reloading model")
            self._log_ui("Reloading model after sleep to restore GPU state…")
            self._model_controller._on_reload_model()

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
            self._service.unload()
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
        app = QApplication.instance()
        if app is not None:
            app.quit()
