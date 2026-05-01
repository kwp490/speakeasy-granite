"""Responsive status cards for the main SpeakEasy window."""

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
    QVBoxLayout,
    QWidget,
)

from .theme import (
    Color,
    Font,
    Motion,
    Size,
    Spacing,
    load_icon,
    status_card_hover_style,
    status_card_style,
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


class _ValueLine(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(Spacing.XS)
        self._dot_label: Optional[QLabel] = None
        self._dot_effect: Optional[QGraphicsOpacityEffect] = None
        self._dot_animation: Optional[QPropertyAnimation] = None

    def set_values(
        self,
        prefix_values: list[tuple[str, Optional[str]]],
        state_text: str,
        dot_color: str,
        pulsing: bool,
    ) -> None:
        self._stop_pulse()
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for index, (text, color) in enumerate(prefix_values):
            self._layout.addWidget(self._text_label(text, color or Color.TEXT_PRIMARY))
            if index < len(prefix_values) - 1:
                self._layout.addWidget(self._text_label("·", Color.TEXT_MUTED))

        if prefix_values:
            self._layout.addWidget(self._text_label("·", Color.TEXT_MUTED))

        dot_label = self._text_label(_dot_html(dot_color), Color.TEXT_PRIMARY, rich=True)
        self._layout.addWidget(dot_label)
        self._dot_label = dot_label
        self._layout.addWidget(self._text_label(state_text, Color.TEXT_PRIMARY))
        self._layout.addStretch()

        if pulsing:
            self._start_pulse()

    def _text_label(self, text: str, color: str, rich: bool = False) -> QLabel:
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText)
        label.setText(text if rich else str(text))
        label.setFont(QFont(Font.FAMILY, Font.BODY[0], QFont.Weight.Medium))
        label.setStyleSheet(f"color: {color}; background: transparent;")
        label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        return label

    def _start_pulse(self) -> None:
        if self._dot_label is None:
            return
        effect = QGraphicsOpacityEffect(self._dot_label)
        effect.setOpacity(1.0)
        self._dot_label.setGraphicsEffect(effect)
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
        if self._dot_label is not None:
            self._dot_label.setGraphicsEffect(None)
        self._dot_effect = None


class _StatusCard(QFrame):
    clicked = Signal()

    def __init__(self, icon_name: str, label: str, clickable: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._label_text = label
        self._clickable = clickable
        self._wide = True
        self._icon = QLabel()
        self._label = QLabel(label)
        self._value_line = _ValueLine()

        self.setObjectName("StatusCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if clickable else Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(status_card_hover_style() if clickable else status_card_style())
        self._label.setStyleSheet(f"color: {Color.TEXT_MUTED}; background: transparent;")
        self._label.setFont(QFont(Font.FAMILY, Font.LABEL[0], QFont.Weight.Medium))
        self.set_mode(True)

    def set_mode(self, wide: bool) -> None:
        self._wide = wide
        self.setMinimumHeight(Size.STATUS_CARD_MIN_HEIGHT if wide else Size.STATUS_PILL_MIN_HEIGHT)
        self._set_icon(Size.STATUS_ICON_CARD if wide else Size.STATUS_ICON_PILL)

        old_layout = self.layout()
        if old_layout is not None:
            while old_layout.count():
                old_layout.takeAt(0)
            QWidget().setLayout(old_layout)

        if wide:
            layout = QHBoxLayout(self)
            layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
            layout.setSpacing(Spacing.MD)
            layout.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignVCenter)
            text_layout = QVBoxLayout()
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(Spacing.XS)
            self._label.setText(self._label_text)
            text_layout.addWidget(self._label)
            text_layout.addWidget(self._value_line)
            layout.addLayout(text_layout, stretch=1)
        else:
            layout = QHBoxLayout(self)
            layout.setContentsMargins(Spacing.SM, Spacing.XS, Spacing.SM, Spacing.XS)
            layout.setSpacing(Spacing.SM)
            self._label.setText(f"{self._label_text}:")
            layout.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(self._label)
            layout.addWidget(self._value_line, stretch=1)

    def set_values(
        self,
        prefix_values: list[tuple[str, Optional[str]]],
        state_text: str,
        dot_color: str,
        pulsing: bool = False,
    ) -> None:
        self._value_line.set_values(prefix_values, state_text, dot_color, pulsing)

    def set_state_accessibility(self, tooltip: str, description: str) -> None:
        self.setToolTip(tooltip)
        self.setAccessibleName(self._label_text)
        self.setAccessibleDescription(description)

    def _set_icon(self, icon_size: int) -> None:
        pixmap = load_icon(self._icon_name).pixmap(QSize(icon_size, icon_size))
        self._icon.setPixmap(pixmap)
        self._icon.setFixedSize(icon_size, icon_size)
        self._icon.setScaledContents(False)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._clickable and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class StatusPillBar(QWidget):
    ai_model_clicked = Signal()
    pro_mode_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._wide: Optional[bool] = None
        self._ai_card = _StatusCard("brain", "AI Model", clickable=True)
        self._dictation_card = _StatusCard("microphone", "Dictation", clickable=False)
        self._pro_card = _StatusCard("sparkles", "Professional Mode", clickable=True)
        self._ai_card.clicked.connect(self.ai_model_clicked.emit)
        self._pro_card.clicked.connect(self.pro_mode_clicked.emit)
        self._apply_layout(wide=False)

    def set_ai_model(self, name: str, device: str, status: Any, fallback: bool) -> None:
        state_text = _enum_display(status)
        dot_color = _model_dot_color(status, fallback)
        device_label = device.upper()
        device_color = Color.WARNING if fallback else None
        model_name = name.strip() or "Cohere"
        self._ai_card.set_values(
            [(model_name, None), (device_label, device_color)],
            state_text,
            dot_color,
        )
        if fallback:
            tooltip = (
                f"{model_name} transcription engine fell back to CPU because GPU is unavailable. "
                f"Status: {state_text}."
            )
        else:
            tooltip = f"{model_name} transcription engine running on {device_label}. Status: {state_text}."
        description = f"AI Model, {model_name}, {device_label}, {state_text}"
        self._ai_card.set_state_accessibility(tooltip, description)

    def set_dictation(self, state: Any) -> None:
        state_text = _enum_display(state)
        pulsing = _enum_name(state) == "RECORDING"
        self._dictation_card.set_values([], state_text, _dictation_dot_color(state), pulsing)
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
        self._dictation_card.set_state_accessibility(tooltip, f"Dictation, {state_text}")

    def set_pro_mode(self, mode: ProMode, preset_name: Optional[str]) -> None:
        if mode == ProMode.PROCESSING:
            state_text = "Processing…"
            pulsing = True
        elif mode == ProMode.ACTIVE:
            state_text = preset_name or "Active"
            pulsing = False
        else:
            state_text = "Off"
            pulsing = False

        self._pro_card.set_values([], state_text, _pro_dot_color(mode), pulsing)
        if mode == ProMode.PROCESSING:
            preset = preset_name or "active"
            tooltip = f"Cleaning up the latest transcription with the '{preset}' preset."
        elif mode == ProMode.ACTIVE:
            tooltip = f"Professional Mode is active with the '{state_text}' preset."
        else:
            tooltip = "Professional Mode is off."
        self._pro_card.set_state_accessibility(tooltip, f"Professional Mode, {state_text}")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_layout(self.width() > Size.STATUS_LAYOUT_THRESHOLD)

    def _apply_layout(self, wide: bool) -> None:
        if self._wide == wide:
            return
        self._wide = wide
        old_layout = self.layout()
        if old_layout is not None:
            while old_layout.count():
                old_layout.takeAt(0)
            QWidget().setLayout(old_layout)

        layout = QHBoxLayout(self) if wide else QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.SM)
        for card in (self._ai_card, self._dictation_card, self._pro_card):
            card.set_mode(wide)
            layout.addWidget(card, stretch=1 if wide else 0)
