"""
Developer Panel — a snapped-but-movable side window with tabs for
Settings, Realtime Data, Logs, and Pro Mode.

Opened from the gear button on the main window or via a global hotkey.
Closing the panel hides it; reopening restores the last active tab.
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import Qt, QPoint, QSize, Signal, QTimer
from PySide6.QtGui import QCloseEvent, QColor, QFont, QPainter, QPen, QResizeEvent, QMoveEvent, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import Settings
from .settings_dialog import SettingsWidget

if TYPE_CHECKING:
    from .main_window import MainWindow

log = logging.getLogger(__name__)

# Tab keys — must match Settings.dev_panel_active_tab valid values
TAB_SETTINGS = "settings"
TAB_REALTIME = "realtime"
TAB_LOGS = "logs"
TAB_PRO = "pro"


# ═══════════════════════════════════════════════════════════════════════════════
# Token sparkline chart
# ═══════════════════════════════════════════════════════════════════════════════


class TokenSparkline(QWidget):
    """Tiny custom-painted line chart for throughput metrics.

    Designed to show "burst" activity: the caller appends a non-zero sample
    when work happens and a zero sample when idle, producing a spike that
    decays back to the baseline.

    Y-axis uses a *sticky* maximum so the scale only grows within the widget
    lifetime; this prevents the visual creep that auto-rebaseline produces
    when each new sample marginally exceeds prior ones (e.g. CUDA warm-up).

    Optionally draws a horizontal reference line (e.g. 1.0x for "realtime")
    and overlays the current sample + scale ceiling as text.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        value_unit: str = "",
        value_fmt: str = "{:.0f}",
        min_scale: float = 1.0,
        reference_line: Optional[float] = None,
        reference_label: str = "",
    ) -> None:
        super().__init__(parent)
        self._data: list[float] = []
        self._value_unit = value_unit
        self._value_fmt = value_fmt
        self._min_scale = float(min_scale)
        self._sticky_max = float(min_scale)
        self._reference_line = reference_line
        self._reference_label = reference_label
        self.setMinimumHeight(70)
        self.setMinimumWidth(200)

    def set_data(self, data: list[float]) -> None:
        self._data = list(data)
        if self._data:
            cur_max = max(self._data)
            if cur_max > self._sticky_max:
                # Headroom above the new peak so the line doesn't sit on
                # the top edge of the chart.
                self._sticky_max = cur_max * 1.15
        self.update()

    def reset(self) -> None:
        """Clear samples and reset the sticky max back to the floor."""
        self._data = []
        self._sticky_max = self._min_scale
        self.update()

    def paintEvent(self, event) -> None:
        from .theme import Color, Font
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Always paint background + border so the chart frame is visible
        # even before any data arrives.
        p.fillRect(self.rect(), QColor(Color.INPUT_BG))
        border_pen = QPen(QColor(Color.BORDER))
        border_pen.setWidth(1)
        p.setPen(border_pen)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

        if not self._data:
            p.setPen(QColor(Color.TEXT_MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "awaiting samples…")
            p.end()
            return

        w, h = self.width(), self.height()
        pad_top, pad_bot = 4, 4
        plot_h = max(1, h - pad_top - pad_bot)
        max_v = self._sticky_max if self._sticky_max > 0 else self._min_scale

        def y_for(v: float) -> float:
            v = max(0.0, min(v, max_v))
            return h - pad_bot - (v / max_v) * plot_h

        # Reference line (e.g. 1.0x realtime)
        if self._reference_line is not None and self._reference_line <= max_v:
            ref_y = y_for(self._reference_line)
            ref_pen = QPen(QColor(Color.TEXT_MUTED))
            ref_pen.setWidth(1)
            ref_pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(ref_pen)
            p.drawLine(0, int(ref_y), w, int(ref_y))
            if self._reference_label:
                p.setFont(QFont(Font.FAMILY, max(7, Font.LABEL[0] - 1)))
                p.drawText(4, int(ref_y) - 2, self._reference_label)

        # Data line
        step = w / max(len(self._data) - 1, 1)
        pen = QPen(QColor(Color.PRIMARY))
        pen.setWidth(2)
        p.setPen(pen)
        prev = None
        for i, v in enumerate(self._data):
            x = i * step
            y = y_for(v)
            if prev is not None:
                p.drawLine(int(prev[0]), int(prev[1]), int(x), int(y))
            prev = (x, y)

        # Top-right overlay: current value and scale ceiling
        p.setFont(QFont(Font.FAMILY, max(7, Font.LABEL[0] - 1)))
        p.setPen(QColor(Color.TEXT_MUTED))
        cur = self._data[-1]
        unit = self._value_unit
        cur_text = f"now {self._value_fmt.format(cur)}{unit}"
        max_text = f"max {self._value_fmt.format(max_v)}{unit}"
        fm = p.fontMetrics()
        p.drawText(w - fm.horizontalAdvance(cur_text) - 4, pad_top + fm.ascent(), cur_text)
        p.drawText(
            w - fm.horizontalAdvance(max_text) - 4,
            pad_top + fm.ascent() + fm.height(),
            max_text,
        )
        p.end()


# ═══════════════════════════════════════════════════════════════════════════════
# Realtime Data widget
# ═══════════════════════════════════════════════════════════════════════════════


class RealtimeDataWidget(QWidget):
    """Live engine status, RAM/VRAM/GPU metrics, audio meter, ASR + LLM throughput."""

    reload_model_requested = Signal()
    validate_requested = Signal()

    TOKEN_HISTORY_LEN = 60  # last 60 samples for sparklines

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._asr_tok_history: list[float] = []
        self._llm_tok_history: list[float] = []
        # Last seen inference/call sequence numbers — used to dedupe
        # sparkline samples between resource-monitor polls.
        self._last_asr_seq: int = 0
        self._last_llm_seq: int = 0
        self._build_ui()

    def _build_ui(self) -> None:
        from .theme import Color, Font, Size, Spacing, make_section

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.XL)

        # ── Model Engine section ─────────────────────────────────────────────
        engine_sec, engine_form = make_section("Model Engine", self)

        self._lbl_engine = QLabel("Engine: —  \u00b7  Device: —")
        self._lbl_engine.setFont(QFont(Font.FAMILY, Font.BODY[0]))
        engine_form.addRow("Engine / Device", self._lbl_engine)

        self._lbl_model_status = QLabel("Status: Not loaded")
        self._lbl_model_status.setFont(QFont(Font.FAMILY, Font.BODY[0]))
        self._lbl_model_status.setTextFormat(Qt.TextFormat.RichText)
        engine_form.addRow("Status", self._lbl_model_status)

        self._lbl_ram = QLabel("RAM: —")
        self._lbl_ram.setFont(QFont(Font.FAMILY, Font.LABEL[0]))
        self._pb_ram = QProgressBar()
        self._pb_ram.setMinimum(0)
        self._pb_ram.setMaximum(100)
        self._pb_ram.setValue(0)
        self._pb_ram.setFixedHeight(Size.PROGRESS_BAR_HEIGHT)
        self._pb_ram.setTextVisible(False)
        engine_form.addRow("RAM", self._build_metric_row(self._lbl_ram, self._pb_ram))

        self._lbl_vram = QLabel("VRAM: —")
        self._lbl_vram.setFont(QFont(Font.FAMILY, Font.LABEL[0]))
        self._pb_vram = QProgressBar()
        self._pb_vram.setMinimum(0)
        self._pb_vram.setMaximum(100)
        self._pb_vram.setValue(0)
        self._pb_vram.setFixedHeight(Size.PROGRESS_BAR_HEIGHT)
        self._pb_vram.setTextVisible(False)
        engine_form.addRow("VRAM", self._build_metric_row(self._lbl_vram, self._pb_vram))

        self._lbl_gpu_info = QLabel("GPU: —")
        self._lbl_gpu_info.setFont(QFont(Font.FAMILY, Font.LABEL[0]))
        engine_form.addRow("GPU", self._lbl_gpu_info)

        btn_row_engine = QHBoxLayout()
        self._btn_reload = QPushButton("Reload Model")
        self._btn_reload.clicked.connect(self.reload_model_requested)
        self._btn_validate = QPushButton("Validate")
        self._btn_validate.clicked.connect(self.validate_requested)
        btn_row_engine.addWidget(self._btn_reload)
        btn_row_engine.addWidget(self._btn_validate)
        btn_row_engine.addStretch()
        engine_sec.layout().addLayout(btn_row_engine)

        layout.addWidget(engine_sec)

        # ── ASR Throughput section (Cohere) ─────────────────────────────────
        asr_sec, asr_form = make_section("ASR Throughput (Cohere)", self)

        self._lbl_asr_rtf = QLabel("0.0x realtime")
        self._lbl_asr_rtf.setFont(QFont(Font.FAMILY, Font.BODY[0]))
        asr_form.addRow("Realtime factor", self._lbl_asr_rtf)

        self._lbl_asr_tok_rate = QLabel("0 tok/s")
        self._lbl_asr_tok_rate.setFont(QFont(Font.FAMILY, Font.LABEL[0]))
        asr_form.addRow("Decoder rate", self._lbl_asr_tok_rate)

        self._lbl_asr_total_tok = QLabel("0 tokens")
        self._lbl_asr_total_tok.setFont(QFont(Font.FAMILY, Font.LABEL[0]))
        asr_form.addRow("Total tokens", self._lbl_asr_total_tok)

        self._lbl_asr_total_audio = QLabel("0.0s audio")
        self._lbl_asr_total_audio.setFont(QFont(Font.FAMILY, Font.LABEL[0]))
        asr_form.addRow("Total audio", self._lbl_asr_total_audio)

        self._lbl_asr_sparkline_title = QLabel(
            "Realtime factor over time (audio sec / wall sec)"
        )
        self._lbl_asr_sparkline_title.setFont(QFont(Font.FAMILY, Font.LABEL[0]))
        self._lbl_asr_sparkline_title.setStyleSheet(f"color: {Color.TEXT_MUTED};")
        asr_sec.layout().addWidget(self._lbl_asr_sparkline_title)
        # Plot RTF: more meaningful than tok/s for ASR.  Reference line at
        # 1.0x marks "realtime"; values above are faster than realtime.
        self._asr_sparkline = TokenSparkline(
            self,
            value_unit="x",
            value_fmt="{:.1f}",
            min_scale=2.0,
            reference_line=1.0,
            reference_label="1.0x realtime",
        )
        asr_sec.layout().addWidget(self._asr_sparkline)

        layout.addWidget(asr_sec)

        # ── LLM Throughput section (Professional Mode) ───────────────────
        tok_sec, tok_form = make_section("LLM Throughput (Pro Mode)", self)

        self._lbl_tok_rate = QLabel("0 tok/s")
        self._lbl_tok_rate.setFont(QFont(Font.FAMILY, Font.BODY[0]))
        tok_form.addRow("Rate", self._lbl_tok_rate)

        self._lbl_tok_in = QLabel("0 in")
        self._lbl_tok_in.setFont(QFont(Font.FAMILY, Font.LABEL[0]))
        tok_form.addRow("Tokens in", self._lbl_tok_in)

        self._lbl_tok_out = QLabel("0 out")
        self._lbl_tok_out.setFont(QFont(Font.FAMILY, Font.LABEL[0]))
        tok_form.addRow("Tokens out", self._lbl_tok_out)

        self._lbl_llm_sparkline_title = QLabel("Token rate over time (tok/s)")
        self._lbl_llm_sparkline_title.setFont(QFont(Font.FAMILY, Font.LABEL[0]))
        self._lbl_llm_sparkline_title.setStyleSheet(f"color: {Color.TEXT_MUTED};")
        tok_sec.layout().addWidget(self._lbl_llm_sparkline_title)
        self._sparkline = TokenSparkline(
            self,
            value_unit=" tok/s",
            value_fmt="{:.0f}",
            min_scale=50.0,
        )
        tok_sec.layout().addWidget(self._sparkline)

        layout.addWidget(tok_sec)

        layout.addStretch()

    def _build_metric_row(self, label: QLabel, bar: QProgressBar) -> QWidget:
        from .theme import Spacing
        w = QWidget(self)
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(Spacing.SM)
        h.addWidget(label)
        h.addWidget(bar, stretch=1)
        return w

    # ── Update methods called by MainWindow ───────────────────────────────────

    def update_engine_status(self, engine: str, device: str, status: str, color: str) -> None:
        device_label = "GPU" if device == "cuda" else "CPU"
        self._lbl_engine.setText(f"Engine: {engine}  \u00b7  Device: {device_label}")
        self._lbl_model_status.setText(
            f'Status: <span style="color:{color}"><b>{status}</b></span>'
        )

    @staticmethod
    def _color_for_percent(pct: float) -> str:
        from .theme import Color
        if pct >= 90:
            return Color.DANGER
        if pct >= 75:
            return Color.WARNING
        return Color.PRIMARY

    @staticmethod
    def _bar_style(pct: float) -> str:
        from .theme import Color
        c = RealtimeDataWidget._color_for_percent(pct)
        return (
            f"QProgressBar {{ border: 1px solid {Color.BORDER}; "
            f"border-radius: 3px; background: {Color.INPUT_BG}; }}"
            f"QProgressBar::chunk {{ background-color: {c}; "
            f"border-radius: 3px; }}"
        )

    def update_ram(self, used_gb: float, total_gb: float, percent: float) -> None:
        if total_gb > 0:
            self._lbl_ram.setText(
                f"RAM: {used_gb:.1f} / {total_gb:.1f} GB ({percent:.0f}%)"
            )
            self._pb_ram.setValue(int(percent))
            self._pb_ram.setStyleSheet(self._bar_style(percent))
        else:
            self._lbl_ram.setText("RAM: —")
            self._pb_ram.setValue(0)

    def update_vram(self, used_gb: float, total_gb: float, percent: float, color: str = "") -> None:
        if total_gb > 0:
            self._lbl_vram.setText(
                f"VRAM: {used_gb:.1f} / {total_gb:.1f} GB ({percent:.0f}%)"
            )
            self._pb_vram.setValue(int(percent))
            self._pb_vram.setStyleSheet(self._bar_style(percent))
        else:
            self._lbl_vram.setText("VRAM: —")
            self._pb_vram.setValue(0)

    def update_gpu(self, label: str) -> None:
        self._lbl_gpu_info.setText(f"GPU: {label}")

    def update_asr_tokens(self, tok_per_sec: float, total_tokens: int,
                           total_audio_sec: float, realtime_factor: float,
                           seq: int = 0) -> None:
        """Update ASR (Cohere) throughput section.

        The sparkline plots **realtime factor** (audio sec / wall sec) over
        time — the standard performance metric for ASR.  ``seq`` is a
        monotonically increasing inference counter from the engine: each
        poll appends a sample to the sparkline, the value being the new
        ``realtime_factor`` if a new inference completed since the last
        poll, otherwise ``0`` so the line falls back to the baseline
        between transcription bursts.

        When ``seq == 0`` (legacy callers / direct unit-test use) the
        widget falls back to the older "append non-zero only" behavior so
        existing tests keep working.
        """
        self._lbl_asr_tok_rate.setText(f"{tok_per_sec:.0f} tok/s")
        self._lbl_asr_rtf.setText(f"{realtime_factor:.1f}x realtime")
        self._lbl_asr_total_tok.setText(f"{total_tokens:,} tokens")
        self._lbl_asr_total_audio.setText(f"{total_audio_sec:.1f}s audio")
        if seq > 0:
            # Skip the very first poll if no inference has happened yet —
            # otherwise we'd seed the buffer with zeros while idle.
            if seq != self._last_asr_seq:
                sample = realtime_factor
                self._last_asr_seq = seq
            elif self._asr_tok_history:
                sample = 0.0
            else:
                return
            self._asr_tok_history.append(sample)
            if len(self._asr_tok_history) > self.TOKEN_HISTORY_LEN:
                self._asr_tok_history.pop(0)
            self._asr_sparkline.set_data(self._asr_tok_history)
        elif tok_per_sec > 0:
            # Legacy / test path: keep historical "append non-zero rate"
            # behavior so existing unit tests (which call this directly
            # without a seq argument) keep passing.
            self._asr_tok_history.append(tok_per_sec)
            if len(self._asr_tok_history) > self.TOKEN_HISTORY_LEN:
                self._asr_tok_history.pop(0)
            self._asr_sparkline.set_data(self._asr_tok_history)

    def update_tokens(self, tok_per_sec: float, tokens_in: int, tokens_out: int,
                      seq: int = 0) -> None:
        """Update LLM (Professional Mode) throughput section.

        See :meth:`update_asr_tokens` for the seq / spike-and-zero semantics.
        For LLMs the plotted metric is the conventional ``tok/s``.
        """
        self._lbl_tok_rate.setText(f"{tok_per_sec:.0f} tok/s")
        self._lbl_tok_in.setText(f"{tokens_in:,} in")
        self._lbl_tok_out.setText(f"{tokens_out:,} out")
        if seq > 0:
            if seq != self._last_llm_seq:
                sample = tok_per_sec
                self._last_llm_seq = seq
            elif self._llm_tok_history:
                sample = 0.0
            else:
                return
            self._llm_tok_history.append(sample)
            if len(self._llm_tok_history) > self.TOKEN_HISTORY_LEN:
                self._llm_tok_history.pop(0)
            self._sparkline.set_data(self._llm_tok_history)
        elif tok_per_sec > 0:
            # Legacy / test path
            self._llm_tok_history.append(tok_per_sec)
            if len(self._llm_tok_history) > self.TOKEN_HISTORY_LEN:
                self._llm_tok_history.pop(0)
            self._sparkline.set_data(self._llm_tok_history)


# ═══════════════════════════════════════════════════════════════════════════════
# Color-coded log view
# ═══════════════════════════════════════════════════════════════════════════════


class ColorCodedLogView(QPlainTextEdit):
    """QPlainTextEdit that detects log level keywords and colors the line."""

    LEVEL_COLORS: dict[str, str] = {}  # populated lazily

    @classmethod
    def _ensure_colors(cls) -> None:
        if not cls.LEVEL_COLORS:
            from .theme import Color
            cls.LEVEL_COLORS = {
                "ERROR":    Color.LOG_ERROR,
                "CRITICAL": Color.LOG_ERROR,
                "WARNING":  Color.LOG_WARN,
                "WARN":     Color.LOG_WARN,
                "INFO":     Color.LOG_INFO,
                "DEBUG":    Color.TEXT_MUTED,
            }

    def append_log_line(self, line: str) -> None:
        color = self._color_for(line)
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.document().isEmpty():
            cursor.insertBlock()
        cursor.setCharFormat(fmt)
        cursor.insertText(line)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _color_for(self, line: str) -> QColor:
        self._ensure_colors()
        head = line[:30].upper()
        for keyword, color_hex in self.LEVEL_COLORS.items():
            if keyword in head:
                return QColor(color_hex)
        from .theme import Color
        return QColor(Color.LOG_INFO)


# ═══════════════════════════════════════════════════════════════════════════════
# Logs widget
# ═══════════════════════════════════════════════════════════════════════════════


class LogsWidget(QWidget):
    """Tab page wrapping the ColorCodedLogView + Clear/Copy buttons."""

    clear_requested = Signal()
    copy_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        from .theme import Font, Spacing

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.XS, Spacing.XS, Spacing.XS, Spacing.XS)

        log_header = QHBoxLayout()
        log_header.addStretch()
        btn_clear = QPushButton("\U0001f5d1  Clear Logs")
        btn_clear.clicked.connect(self.clear_requested)
        btn_copy = QPushButton("\U0001f4cb  Copy Logs")
        btn_copy.clicked.connect(self.copy_requested)
        log_header.addWidget(btn_clear)
        log_header.addWidget(btn_copy)
        layout.addLayout(log_header)

        self._log_text = ColorCodedLogView()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumBlockCount(500)
        self._log_text.setFont(QFont(Font.FAMILY_MONO, Font.LOG[0]))
        self._log_text.setPlaceholderText("No logs yet. Activity will appear here as the app runs.")
        layout.addWidget(self._log_text)

    @property
    def log_text(self) -> ColorCodedLogView:
        return self._log_text


# ═══════════════════════════════════════════════════════════════════════════════
# Developer Panel
# ═══════════════════════════════════════════════════════════════════════════════


class DeveloperPanel(QWidget):
    """Snapped-but-movable side window with tabbed dev tools."""

    closed = Signal()

    SNAP_THRESHOLD_PX = 30  # within this distance of the main window's right edge → re-snap

    def __init__(self, settings: Settings, main_window: "MainWindow") -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("Developer Panel")
        self.settings = settings
        self._main_window = main_window
        self._snapped = settings.dev_panel_snapped
        self._suppress_move_persist = False  # True during programmatic moves
        self._build_ui()
        self._wire_signals()
        self.resize(settings.dev_panel_width, settings.dev_panel_height)
        self.setMinimumWidth(540)
        self.setMaximumWidth(800)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        from .theme import Font, Spacing
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        layout.setSpacing(Spacing.SM)

        self._tabs = QTabWidget()
        self._tabs.setFont(QFont(Font.FAMILY, Font.BODY[0]))
        layout.addWidget(self._tabs)

        # Tab 0: Settings
        self._settings_widget = SettingsWidget(self.settings, self)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(self._settings_widget)
        self._tabs.addTab(settings_scroll, "\u2699\ufe0f  Settings")

        # Tab 1: Realtime Data
        self.realtime_widget = RealtimeDataWidget(self)
        self._tabs.addTab(self.realtime_widget, "\U0001f4ca  Realtime Data")

        # Tab 2: Logs
        self.logs_widget = LogsWidget(self)
        self._tabs.addTab(self.logs_widget, "\U0001f4cb  Logs")

        # Tab 3: Pro Mode
        from .pro_mode_widget import ProModeWidget  # noqa: F811

        self.pro_mode_widget = ProModeWidget(
            settings=self.settings,
            on_disclosure_required=self._show_pro_disclosure,
            parent=self,
        )
        pro_scroll = QScrollArea()
        pro_scroll.setWidgetResizable(True)
        pro_scroll.setWidget(self.pro_mode_widget)
        self._tabs.addTab(pro_scroll, "\U0001f4bc  Pro Mode")

        # Restore last active tab
        self._tabs.setCurrentIndex(self._tab_key_to_index(self.settings.dev_panel_active_tab))
        self._tabs.currentChanged.connect(self._on_tab_changed)

    def _wire_signals(self) -> None:
        # Settings tab
        self._settings_widget.reload_model_requested.connect(self._main_window._on_reload_model)
        self._settings_widget.settings_applied.connect(self._main_window._apply_settings)
        # Realtime tab
        self.realtime_widget.reload_model_requested.connect(self._main_window._on_reload_model)
        self.realtime_widget.validate_requested.connect(self._main_window._on_validate)
        # Logs tab
        self.logs_widget.clear_requested.connect(self._main_window._on_clear_logs)
        self.logs_widget.copy_requested.connect(self._main_window._on_copy_logs)
        # Pro Mode tab
        self.pro_mode_widget.settings_applied.connect(self._main_window._on_pro_mode_applied)
        self.pro_mode_widget.presets_changed.connect(self._main_window._populate_pro_preset_combo)

    def _show_pro_disclosure(self) -> bool:
        """Show data-privacy disclosure; return True if the user accepts."""
        from PySide6.QtWidgets import QMessageBox

        disc = QMessageBox(self)
        disc.setIcon(QMessageBox.Icon.Warning)
        disc.setWindowTitle("Data Privacy Notice: Optional Professional Mode")
        disc.setText(
            "All transcription is local to this machine and is not stored, "
            "externally transmitted, or logged."
        )
        disc.setInformativeText(
            "If you choose to enable <b>Professional Mode</b>, dictation results will "
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

    # ── Snapping ──────────────────────────────────────────────────────────────

    def show_snapped(self) -> None:
        """Show the panel; if snapped, position it to the right of the main window."""
        if self._snapped:
            self._snap_to_main()
        self.show()
        self.raise_()
        self.activateWindow()

    def _snap_to_main(self) -> None:
        mw = self._main_window
        geom = mw.frameGeometry()
        target = QPoint(geom.right() + 1, geom.top())
        self._suppress_move_persist = True
        self.move(target)
        self.resize(self.settings.dev_panel_width, geom.height())
        self._suppress_move_persist = False

    def on_main_window_moved(self) -> None:
        """Called by MainWindow when its position or size changes."""
        if self._snapped and self.isVisible():
            self._snap_to_main()

    # ── Tabs ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _tab_key_to_index(key: str) -> int:
        return {TAB_SETTINGS: 0, TAB_REALTIME: 1, TAB_LOGS: 2, TAB_PRO: 3}.get(key, 0)

    @staticmethod
    def _index_to_tab_key(idx: int) -> str:
        return [TAB_SETTINGS, TAB_REALTIME, TAB_LOGS, TAB_PRO][idx] if 0 <= idx < 4 else TAB_SETTINGS

    def _on_tab_changed(self, idx: int) -> None:
        self.settings.dev_panel_active_tab = self._index_to_tab_key(idx)
        self.settings.save()

    def activate_tab(self, key: str) -> None:
        """Switch to the tab identified by *key* (e.g. TAB_PRO)."""
        self._tabs.setCurrentIndex(self._tab_key_to_index(key))

    # ── Geometry persistence ──────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:
        # Hide instead of destroying so reopen is fast
        event.ignore()
        self.hide()
        self.closed.emit()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if not self._suppress_move_persist:
            self.settings.dev_panel_width = self.width()
            self.settings.dev_panel_height = self.height()
            self.settings.save()

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        if self._suppress_move_persist:
            return
        # User dragged the panel — check if they pulled it away from the main window's edge
        mw_right = self._main_window.frameGeometry().right()
        delta = abs(self.frameGeometry().left() - (mw_right + 1))
        new_snapped = delta <= self.SNAP_THRESHOLD_PX
        if new_snapped != self._snapped:
            self._snapped = new_snapped
            self.settings.dev_panel_snapped = new_snapped
            self.settings.save()
