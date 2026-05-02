"""Compact status bar for the main SpeakEasy window."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from .theme import (
    Color,
    Font,
    Motion,
    Spacing,
    compact_status_bar_style,
    load_icon,
)


class ProMode(str, Enum):
    OFF = "off"
    PROCESSING = "processing"
    ACTIVE = "active"


def _enum_name(value: Any) -> str:
    return str(getattr(value, "name", value))


def _enum_display(value: Any) -> str:
    display = getattr(value, "display", None)
    if display is not None:
        return str(display)
    return str(getattr(value, "value", value))


def _dot_html(color: str) -> str:
    return f'<span style="color:{color};">&#9679;</span>'


def _model_dot_color(status: Any, fallback: bool) -> str:
    if fallback:
        return Color.WARNING
    name = _enum_name(status)
    if name in {"READY", "VALIDATED"}:
        return Color.SUCCESS
    if name in {"LOADING", "VALIDATING"}:
        return Color.INFO
    if name == "ERROR":
        return Color.DANGER
    return Color.TEXT_MUTED


def _dictation_dot_color(state: Any) -> str:
    name = _enum_name(state)
    if name == "RECORDING":
        return Color.DANGER
    if name == "PROCESSING":
        return Color.INFO
    if name == "SUCCESS":
        return Color.SUCCESS
    if name == "ERROR":
        return Color.DANGER
    return Color.TEXT_MUTED


def _pro_dot_color(mode: ProMode) -> str:
    if mode == ProMode.PROCESSING:
        return Color.INFO
    if mode == ProMode.ACTIVE:
        return Color.SUCCESS
    return Color.TEXT_MUTED


class _StatusSegment(QWidget):
    """A single segment in the compact status bar."""

    clicked = Signal()

    def __init__(
        self,
        icon_name: str,
        label: str,
        clickable: bool,
        accessible_name: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._clickable = clickable
        self._accessible_name = accessible_name
        self.setObjectName("StatusSegment")
        if clickable:
            self.setStyleSheet(f"""
                QWidget#StatusSegment {{
                    background-color: transparent;
                    border-radius: 6px;
                }}
                QWidget#StatusSegment:hover {{
                    background-color: rgba(27, 49, 71, 0.62);
                }}
            """)

        self.setCursor(
            Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor
        )
        self.setFocusPolicy(
            Qt.FocusPolicy.StrongFocus if clickable else Qt.FocusPolicy.NoFocus
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.XS)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel()
        icon_size = 22
        pixmap = load_icon(icon_name).pixmap(QSize(icon_size, icon_size))
        icon_label.setPixmap(pixmap)
        icon_label.setFixedSize(icon_size, icon_size)
        icon_label.setStyleSheet("background: transparent;")
        layout.addWidget(icon_label)

        self._label = QLabel(f"{label}:")
        self._label.setFont(QFont(Font.FAMILY, Font.BODY[0], QFont.Weight.Medium))
        self._label.setStyleSheet(f"color: {Color.TEXT_MUTED}; background: transparent;")
        self._label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._label)

        self._value = QLabel()
        self._value.setFont(QFont(Font.FAMILY, Font.BODY[0], QFont.Weight.Medium))
        self._value.setStyleSheet(f"color: {Color.TEXT_PRIMARY}; background: transparent;")
        self._value.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._value)

        self._dot = QLabel()
        self._dot.setTextFormat(Qt.TextFormat.RichText)
        self._dot.setFont(QFont(Font.FAMILY, Font.BODY[0]))
        self._dot.setStyleSheet("background: transparent;")
        self._dot.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._dot)

        self._state = QLabel()
        self._state.setFont(QFont(Font.FAMILY, Font.BODY[0], QFont.Weight.Medium))
        self._state.setStyleSheet(f"color: {Color.TEXT_PRIMARY}; background: transparent;")
        self._state.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._state)

        self._dot_effect: Optional[QGraphicsOpacityEffect] = None
        self._dot_animation: Optional[QPropertyAnimation] = None

    def set_values(
        self,
        value_text: str,
        state_text: str,
        dot_color: str,
        pulsing: bool = False,
        value_color: Optional[str] = None,
    ) -> None:
        self._value.setText(value_text)
        self._value.setStyleSheet(
            f"color: {value_color or Color.TEXT_PRIMARY}; background: transparent;"
        )
        self._value.setVisible(bool(value_text))
        self._dot.setText(_dot_html(dot_color))
        self._state.setText(state_text)
        self._stop_pulse()
        if pulsing:
            self._start_pulse()

    def set_state_accessibility(self, tooltip: str, description: str) -> None:
        self.setToolTip(tooltip)
        self.setAccessibleName(self._accessible_name)
        self.setAccessibleDescription(description)

    def _start_pulse(self) -> None:
        effect = QGraphicsOpacityEffect(self._dot)
        effect.setOpacity(1.0)
        self._dot.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setStartValue(0.4)
        animation.setKeyValueAt(0.5, 1.0)
        animation.setEndValue(0.4)
        animation.setDuration(Motion.DURATION_NORMAL_MS * 7)
        animation.setLoopCount(-1)
        animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        animation.start()
        self._dot_effect = effect
        self._dot_animation = animation

    def _stop_pulse(self) -> None:
        if self._dot_animation is not None:
            self._dot_animation.stop()
            self._dot_animation.deleteLater()
            self._dot_animation = None
        self._dot.setGraphicsEffect(None)
        self._dot_effect = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._clickable and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Space,
        ):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class StatusPillBar(QWidget):
    """Compact horizontal status bar showing Model, Mic, and Mode segments."""

    ai_model_clicked = Signal()
    pro_mode_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._container = QFrame(self)
        self._container.setObjectName("CompactStatusBar")
        self._container.setStyleSheet(compact_status_bar_style())
        self._container.setMinimumHeight(52)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._container)

        layout = QHBoxLayout(self._container)
        layout.setContentsMargins(Spacing.LG, Spacing.SM, Spacing.LG, Spacing.SM)
        layout.setSpacing(Spacing.MD)

        self._ai_segment = _StatusSegment(
            "brain", "Model", clickable=True, accessible_name="AI Model",
        )
        self._ai_segment.clicked.connect(self.ai_model_clicked.emit)
        layout.addWidget(self._ai_segment, stretch=1)

        layout.addWidget(self._make_separator())

        self._dictation_segment = _StatusSegment(
            "microphone", "Mic", clickable=False, accessible_name="Dictation",
        )
        layout.addWidget(self._dictation_segment, stretch=1)

        layout.addWidget(self._make_separator())

        self._pro_segment = _StatusSegment(
            "sparkles", "Mode", clickable=True, accessible_name="Professional Mode",
        )
        self._pro_segment.clicked.connect(self.pro_mode_clicked.emit)
        layout.addWidget(self._pro_segment, stretch=1)

    @staticmethod
    def _make_separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setStyleSheet(f"color: {Color.BORDER_SUBTLE}; background: transparent;")
        sep.setFixedWidth(1)
        sep.setFixedHeight(30)
        return sep

    def set_ai_model(self, name: str, device: str, status: Any, fallback: bool) -> None:
        state_text = _enum_display(status)
        dot_color = _model_dot_color(status, fallback)
        device_label = device.upper()
        model_name = name.strip() or "Granite"
        value_text = f"{model_name} ({device_label})"
        value_color = Color.WARNING if fallback else None
        self._ai_segment.set_values(value_text, state_text, dot_color, value_color=value_color)
        if fallback:
            tooltip = (
                f"{model_name} transcription engine fell back to CPU because GPU is unavailable. "
                f"Status: {state_text}."
            )
        else:
            tooltip = f"{model_name} transcription engine running on {device_label}. Status: {state_text}."
        description = f"AI Model, {model_name}, {device_label}, {state_text}"
        self._ai_segment.set_state_accessibility(tooltip, description)

    def set_dictation(self, state: Any) -> None:
        state_text = _enum_display(state)
        pulsing = _enum_name(state) == "RECORDING"
        self._dictation_segment.set_values(
            "", state_text, _dictation_dot_color(state), pulsing,
        )
        if pulsing:
            tooltip = "Currently recording audio. Press Ctrl+Alt+P to stop."
        elif _enum_name(state) == "PROCESSING":
            tooltip = "Transcribing the latest recording."
        elif _enum_name(state) == "SUCCESS":
            tooltip = "Latest dictation completed successfully."
        elif _enum_name(state) == "ERROR":
            tooltip = "The latest dictation ended with an error."
        else:
            tooltip = "Dictation is idle. Press Ctrl+Alt+P to start."
        self._dictation_segment.set_state_accessibility(tooltip, f"Dictation, {state_text}")

    def set_pro_mode(self, mode: ProMode, preset_name: Optional[str]) -> None:
        if mode == ProMode.PROCESSING:
            state_text = "Processing\u2026"
            pulsing = True
        elif mode == ProMode.ACTIVE:
            state_text = preset_name or "Active"
            pulsing = False
        else:
            state_text = "Off"
            pulsing = False

        self._pro_segment.set_values("", state_text, _pro_dot_color(mode), pulsing)
        if mode == ProMode.PROCESSING:
            preset = preset_name or "active"
            tooltip = f"Cleaning up the latest transcription with the '{preset}' preset."
        elif mode == ProMode.ACTIVE:
            tooltip = f"Professional Mode is active with the '{state_text}' preset."
        else:
            tooltip = "Professional Mode is off."
        self._pro_segment.set_state_accessibility(tooltip, f"Professional Mode, {state_text}")
