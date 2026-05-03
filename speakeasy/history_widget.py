"""History tab widget for the Developer Panel.

Displays transcription history entries with timestamps, status icons,
and copy buttons.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .clipboard import set_clipboard_text
from .theme import Color, Size, Spacing


class _WordWrapLabel(QLabel):
    """QLabel that correctly grows its row when word-wrap causes multiple lines.

    A plain QLabel with ``setWordWrap(True)`` inside a QHBoxLayout inside a
    QScrollArea frequently fails to propagate its height-for-width requirement,
    leaving the row clipped.  This subclass updates its own ``minimumHeight``
    whenever its width changes, which the parent layout then respects.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWordWrap(True)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.width() > 0:
            self.setMinimumHeight(self.sizeHint().height())


class _HistoryEntry(QWidget):
    """Single final row in the transcription history."""

    _SUCCESS_ICON = "\u2705"
    _ERROR_ICON = "\u274c"

    def __init__(
        self,
        timestamp: str,
        text: str,
        success: bool,
        parent: Optional[QWidget] = None,
        original_text: Optional[str] = None,
    ):
        super().__init__(parent)
        self._text = text
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(Spacing.XS, Spacing.XS, Spacing.XS, Spacing.XS)

        self._time_label = QLabel(f"<b>{timestamp}</b>")
        self._time_label.setFixedWidth(70)
        self._status_label = QLabel(self._status_text(success))
        self._status_label.setFixedWidth(60)

        self._text_widget = self._build_text_widget(text, original_text)

        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setMinimumWidth(70)
        self._copy_btn.setFixedHeight(28)
        self._copy_btn.clicked.connect(self._copy)

        row.addWidget(self._time_label)
        row.addWidget(self._status_label)
        row.addWidget(self._text_widget)
        row.addWidget(self._copy_btn)

        outer.addWidget(row_widget)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        separator.setStyleSheet(f"color: {Color.BORDER};")
        separator.setFixedHeight(1)
        outer.addWidget(separator)

    @property
    def text(self) -> str:
        return self._text

    # ── Internals ────────────────────────────────────────────────────────────

    def _status_text(self, success: bool) -> str:
        return self._SUCCESS_ICON if success else self._ERROR_ICON

    def _build_text_widget(self, text: str, original_text: Optional[str]) -> QWidget:
        if original_text is not None:
            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(1)

            orig_display = original_text if len(original_text) <= 120 else original_text[:117] + "\u2026"
            orig_label = _WordWrapLabel(f'<span style="color:{Color.TEXT_MUTED}">Original: {orig_display}</span>')
            orig_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            orig_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text_col.addWidget(orig_label)

            clean_display = text if len(text) <= 120 else text[:117] + "\u2026"
            clean_label = _WordWrapLabel(f"Cleaned: {clean_display}")
            clean_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            clean_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text_col.addWidget(clean_label)

            text_widget = QWidget()
            text_widget.setLayout(text_col)
            text_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            return text_widget

        display = text if len(text) <= 120 else text[:117] + "\u2026"
        label = _WordWrapLabel(display)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _copy(self) -> None:
        set_clipboard_text(self._text)


class HistoryWidget(QWidget):
    """Tab widget displaying transcription history in the Developer Panel."""

    clear_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        layout.setSpacing(Spacing.SM)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch()
        self._btn_clear = QPushButton("Clear History")
        self._btn_clear.setMinimumHeight(Size.BUTTON_HEIGHT)
        self._btn_clear.clicked.connect(self.clear_requested.emit)
        actions.addWidget(self._btn_clear)
        layout.addLayout(actions)

        self._history_content = QWidget()
        self._history_layout = QVBoxLayout(self._history_content)
        self._history_layout.setContentsMargins(0, 0, 0, 0)
        self._history_layout.setSpacing(Spacing.XS)
        self._history_layout.addStretch()

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._history_content)
        layout.addWidget(self._scroll)

    @property
    def history_layout(self) -> QVBoxLayout:
        return self._history_layout

    @property
    def history_content(self) -> QWidget:
        return self._history_content
