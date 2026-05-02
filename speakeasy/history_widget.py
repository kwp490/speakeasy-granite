"""History tab widget for the Developer Panel.

Displays transcription history entries with timestamps, status icons,
and copy buttons. Supports live draft entries during active transcription.
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
    """Single row in the transcription history.

    Supports two modes:

    * Final entry (default): fixed timestamp, status icon, displayed text,
      optional original/cleaned labels for Professional Mode.
    * Live draft (``is_draft=True``): the same row in a provisional state while
      the engine is still transcribing chunks.
    """

    _DRAFT_ICON = "\u23f3"   # hourglass
    _SUCCESS_ICON = "\u2705"
    _ERROR_ICON = "\u274c"

    def __init__(
        self,
        timestamp: str,
        text: str,
        success: bool,
        parent: Optional[QWidget] = None,
        original_text: Optional[str] = None,
        is_draft: bool = False,
    ):
        super().__init__(parent)
        self._text = text
        self._is_draft = is_draft
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
        if is_draft:
            self._copy_btn.setEnabled(False)

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

        if is_draft:
            self._apply_draft_style()

    # ── Public API for draft updates ─────────────────────────────────────────

    @property
    def is_draft(self) -> bool:
        return self._is_draft

    @property
    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text
        self._set_text_widget_text(text)

    def set_progress(self, chunk_index: int, total_chunks: int) -> None:
        if self._is_draft:
            self._status_label.setText(f"{chunk_index}/{total_chunks}")

    def mark_final(self, text: str, success: bool = True,
                   original_text: Optional[str] = None) -> None:
        self._is_draft = False
        self._text = text
        self._status_label.setText(self._status_text(success))
        row_widget = self.layout().itemAt(0).widget()
        layout = row_widget.layout()
        layout.removeWidget(self._text_widget)
        self._text_widget.deleteLater()
        self._text_widget = self._build_text_widget(text, original_text)
        layout.insertWidget(2, self._text_widget)
        self._copy_btn.setEnabled(True)
        self._clear_draft_style()

    def mark_error(self, message: str) -> None:
        self.mark_final(f"Error: {message}", success=False)

    # ── Internals ────────────────────────────────────────────────────────────

    def _status_text(self, success: bool) -> str:
        if self._is_draft:
            return self._DRAFT_ICON
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

    def _set_text_widget_text(self, text: str) -> None:
        if isinstance(self._text_widget, QLabel):
            display = text if len(text) <= 120 else text[:117] + "\u2026"
            self._text_widget.setText(display)

    def _apply_draft_style(self) -> None:
        style = f'color:{Color.TEXT_MUTED}; font-style:italic;'
        if isinstance(self._text_widget, QLabel):
            display = self._text if len(self._text) <= 120 else self._text[:117] + "\u2026"
            self._text_widget.setText(
                f'<span style="{style}">{display}</span>' if display else
                f'<span style="{style}">(listening\u2026)</span>'
            )

    def _clear_draft_style(self) -> None:
        pass

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
