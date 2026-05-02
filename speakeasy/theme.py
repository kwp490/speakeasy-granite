"""
Design tokens for SpeakEasy AI.

Single source of truth for colors, spacing, typography, and stylesheet
fragments. All UI code should reference these tokens — no hardcoded hex
values or magic spacing numbers anywhere else in the codebase.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


ICON_DIR = Path(__file__).parent / "assets" / "icons"


# ── Color tokens ──────────────────────────────────────────────────────────────

class Color:
    # Surfaces
    BACKGROUND = "#0B1624"       # app background (deep navy)
    PANEL = "#0F1E2E"            # cards, group boxes
    PANEL_ELEVATED = "#16283A"   # hover/active surfaces
    PANEL_HOVER = "#1B3147"      # clickable status cards
    BORDER = "#1D3145"           # default border
    BORDER_SUBTLE = "#31455B"    # tab borders, subtle dividers
    INPUT_BG = "#152638"         # text inputs, dropdowns

    # Brand / actions
    PRIMARY = "#2563EB"          # primary buttons, active tabs (blue-600)
    PRIMARY_HOVER = "#1D4ED8"    # blue-700
    PRIMARY_PRESSED = "#1E40AF"  # blue-800

    # Semantic status
    SUCCESS = "#22C55E"          # ready, healthy (green-500)
    WARNING = "#F59E0B"          # caution (amber-500)
    DANGER = "#EF4444"           # errors, quit button (red-500)
    DANGER_HOVER = "#DC2626"     # red-600
    INFO = "#3B82F6"             # informational accents (blue-500)

    # Text
    TEXT_PRIMARY = "#F8FAFC"     # app title, emphasis
    TEXT_HEADING = "#E5EAF2"     # section headers
    TEXT_BODY = "#D1D5DB"        # body text (gray-300)
    TEXT_MUTED = "#9CA3AF"       # labels, secondary text (gray-400)
    TEXT_DISABLED = "#6B7280"    # disabled state (gray-500)
    TEXT_LOG = "#CFCFCF"         # monospace log body

    # Log level accents
    LOG_INFO = TEXT_BODY
    LOG_WARN = WARNING
    LOG_ERROR = DANGER


# ── Spacing tokens (strict 8px grid) ──────────────────────────────────────────

class Spacing:
    """All margins, padding, and gaps must use these values. No exceptions."""
    XS = 4    # tight (icon-to-text, inline label-to-control)
    SM = 8    # base unit (default gap)
    MD = 12   # small section internal gap
    LG = 16   # standard padding (card interior, panel padding)
    SECTION = 20  # vertical gap between sections (per UI correction spec; intentionally off 8px grid)
    XL = 24   # section separation
    XXL = 32  # major separation


# ── Typography tokens ─────────────────────────────────────────────────────────

class Font:
    FAMILY = "Segoe UI"
    FAMILY_MONO = "Consolas"

    # (size_pt, weight)
    APP_TITLE = (16, 600)
    SECTION_HEADER = (14, 600)
    BODY = (10, 400)         # 10pt ≈ 13-14px on Windows
    BODY_EMPHASIS = (10, 500)
    LABEL = (9, 500)         # 9pt ≈ 12px
    LOG = (9, 400)           # mono


# ── Component dimensions ──────────────────────────────────────────────────────

class Size:
    BUTTON_HEIGHT = 36
    BUTTON_HEIGHT_PRIMARY = 64     # Start Recording, prominent CTAs
    GEAR_BUTTON = 76               # settings button minimum width
    INPUT_HEIGHT = 36
    TAB_HEIGHT = 40
    PROGRESS_BAR_HEIGHT = 6        # thin bars in Realtime Data
    STATUS_DOT = 8                 # colored dots in status row
    STATUS_ICON_CARD = 24
    STATUS_ICON_PILL = 18
    STATUS_CARD_MIN_HEIGHT = 52
    STATUS_PILL_MIN_HEIGHT = 28
    STATUS_LAYOUT_THRESHOLD = 640
    SETTING_ROW_MAX_WIDTH = 560
    SETTING_ROW_HEIGHT = 28
    SETTING_ROW_STACKED_HEIGHT = 64
    BORDER_RADIUS_SM = 6
    BORDER_RADIUS_MD = 8
    BORDER_RADIUS_LG = 10          # primary buttons


# ── Animation tokens ──────────────────────────────────────────────────────────

class Motion:
    DURATION_FAST_MS = 150
    DURATION_NORMAL_MS = 200
    EASING = "ease-out"


# ── Stylesheet builders ───────────────────────────────────────────────────────

def load_icon(name: str) -> QIcon:
    """Load an SVG icon from assets/icons/<name>.svg as a QIcon."""
    from PySide6.QtSvg import QSvgRenderer

    icon_path = ICON_DIR / f"{name}.svg"
    QSvgRenderer(str(icon_path))
    return QIcon(str(icon_path))


def status_card_style() -> str:
    """Base panel styling for non-clickable status cards and pills."""
    return f"""
        QFrame#StatusCard {{
            background-color: {Color.PANEL_ELEVATED};
            border: 1px solid {Color.BORDER_SUBTLE};
            border-radius: {Size.BORDER_RADIUS_LG}px;
        }}
        QFrame#StatusCard:focus {{
            border: 2px solid {Color.PRIMARY};
        }}
    """


def status_card_hover_style() -> str:
    """Base plus hover/focus styling for clickable status cards and pills."""
    return f"""
        QFrame#StatusCard {{
            background-color: {Color.PANEL_ELEVATED};
            border: 1px solid {Color.BORDER_SUBTLE};
            border-radius: {Size.BORDER_RADIUS_LG}px;
        }}
        QFrame#StatusCard:hover {{
            background-color: {Color.PANEL_HOVER};
            border-color: {Color.PRIMARY};
        }}
        QFrame#StatusCard:focus {{
            border: 2px solid {Color.PRIMARY};
        }}
    """

def app_stylesheet() -> str:
    """Global QSS applied at QApplication level. Sets baseline for every
    QWidget; specific widgets override as needed."""
    return f"""
        QMainWindow, QWidget#MainContent {{
            background-color: qradialgradient(
                cx: 0.28, cy: 0.18, radius: 1.2,
                fx: 0.28, fy: 0.18,
                stop: 0 {Color.PANEL_ELEVATED},
                stop: 0.45 {Color.PANEL},
                stop: 1 {Color.BACKGROUND}
            );
        }}
        QWidget {{
            color: {Color.TEXT_BODY};
            font-family: '{Font.FAMILY}', sans-serif;
            font-size: {Font.BODY[0]}pt;
        }}

        QGroupBox {{
            background-color: {Color.PANEL};
            border: 1px solid {Color.BORDER};
            border-radius: {Size.BORDER_RADIUS_MD}px;
            margin-top: {Spacing.SM}px;
            padding: {Spacing.MD}px;
            color: {Color.TEXT_HEADING};
            font-weight: 600;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: {Spacing.MD}px;
            padding: 0 {Spacing.SM}px;
        }}

        QLabel {{ background: transparent; }}
        QWidget#MainContent,
        QWidget#SectionContent,
        QWidget#RecordButtonContent,
        QWidget#RecordButtonText,
        QWidget#StatusContent,
        QWidget#StatusSegment {{
            background: transparent;
        }}

        QPushButton {{
            background-color: {Color.PANEL_ELEVATED};
            border: 1px solid {Color.BORDER_SUBTLE};
            border-radius: {Size.BORDER_RADIUS_MD}px;
            padding: {Spacing.SM}px {Spacing.MD}px;
            color: {Color.TEXT_BODY};
            min-height: {Size.BUTTON_HEIGHT - 16}px;
        }}
        QPushButton:hover {{
            background-color: {Color.BORDER_SUBTLE};
            border-color: {Color.PRIMARY};
        }}
        QPushButton:pressed {{ background-color: {Color.BORDER}; }}
        QPushButton:disabled {{ color: {Color.TEXT_DISABLED}; border-color: {Color.BORDER}; }}

        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background-color: {Color.INPUT_BG};
            border: 1px solid {Color.BORDER_SUBTLE};
            border-radius: {Size.BORDER_RADIUS_MD}px;
            padding: {Spacing.SM}px {Spacing.MD}px;
            color: {Color.TEXT_BODY};
            min-height: {Size.INPUT_HEIGHT - 18}px;
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border-color: {Color.PRIMARY};
        }}

        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
            background-color: rgba(21, 38, 56, 0.38);
            border-color: {Color.BORDER};
            color: {Color.TEXT_DISABLED};
        }}

        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox QAbstractItemView {{
            background-color: {Color.PANEL};
            border: 1px solid {Color.BORDER_SUBTLE};
            selection-background-color: {Color.PRIMARY};
            color: {Color.TEXT_BODY};
        }}

        QTabWidget::pane {{
            border: 1px solid {Color.BORDER};
            border-radius: {Size.BORDER_RADIUS_SM}px;
            background-color: {Color.PANEL};
        }}
        QTabBar::tab {{
            background: transparent;
            color: {Color.TEXT_MUTED};
            padding: {Spacing.SM}px {Spacing.LG}px;
            min-height: {Size.TAB_HEIGHT - 16}px;
            border: none;
        }}
        QTabBar::tab:selected {{
            color: {Color.PRIMARY};
            border-bottom: 2px solid {Color.PRIMARY};
        }}
        QTabBar::tab:hover:!selected {{ color: {Color.TEXT_HEADING}; }}

        QPlainTextEdit {{
            background-color: {Color.INPUT_BG};
            border: 1px solid {Color.BORDER};
            border-radius: {Size.BORDER_RADIUS_SM}px;
            color: {Color.TEXT_LOG};
            font-family: '{Font.FAMILY_MONO}', monospace;
            font-size: {Font.LOG[0]}pt;
            padding: {Spacing.SM}px;
        }}

        QProgressBar {{
            border: 1px solid {Color.BORDER};
            border-radius: {Size.BORDER_RADIUS_SM // 2}px;
            background: {Color.INPUT_BG};
            text-align: center;
        }}
        QProgressBar::chunk {{
            background-color: {Color.PRIMARY};
            border-radius: {Size.BORDER_RADIUS_SM // 2}px;
        }}

        QScrollArea {{ background: transparent; border: none; }}

        QScrollBar:vertical {{
            background: {Color.BACKGROUND};
            width: 8px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {Color.BORDER_SUBTLE};
            border-radius: 4px;
            min-height: 20px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}

        QCheckBox {{
            color: {Color.TEXT_BODY};
            spacing: {Spacing.SM}px;
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
        }}
    """


def primary_button_style() -> str:
    """For the Start Recording button and any other prominent CTAs."""
    return f"""
        QPushButton {{
            background-color: qlineargradient(
                x1: 0, y1: 0, x2: 1, y2: 1,
                stop: 0 #2563EB,
                stop: 0.55 #1D4ED8,
                stop: 1 #1652F0
            );
            color: {Color.TEXT_PRIMARY};
            font-size: {Font.SECTION_HEADER[0]}pt;
            font-weight: bold;
            border: 1px solid rgba(96, 165, 250, 0.28);
            border-radius: {Size.BORDER_RADIUS_LG}px;
            min-height: {Size.BUTTON_HEIGHT_PRIMARY}px;
            padding: {Spacing.SM}px {Spacing.LG}px;
        }}
        QPushButton:hover {{
            background-color: qlineargradient(
                x1: 0, y1: 0, x2: 1, y2: 1,
                stop: 0 #2F6FF1,
                stop: 0.55 #2563EB,
                stop: 1 #1D4ED8
            );
        }}
        QPushButton:pressed {{ background-color: {Color.PRIMARY_PRESSED}; }}
        QPushButton:disabled {{
            background-color: {Color.PANEL_ELEVATED};
            color: {Color.TEXT_DISABLED};
        }}
    """


def gear_button_style() -> str:
    """The settings button next to Start Recording."""
    return f"""
        QToolButton, QPushButton {{
            background-color: rgba(21, 38, 56, 0.72);
            color: {Color.TEXT_BODY};
            font-size: {Font.BODY[0]}pt;
            border: 1px solid {Color.BORDER};
            border-radius: {Size.BORDER_RADIUS_LG}px;
            padding: {Spacing.SM}px;
        }}
        QToolButton:hover, QPushButton:hover {{
            background-color: rgba(49, 69, 91, 0.35);
            border-color: {Color.BORDER_SUBTLE};
            color: {Color.TEXT_PRIMARY};
        }}
        QToolButton:pressed, QPushButton:pressed {{ background-color: {Color.BORDER}; }}
        QToolButton:checked, QPushButton:checked {{
            background-color: rgba(37, 99, 235, 0.22);
            border-color: {Color.PRIMARY};
            color: {Color.TEXT_PRIMARY};
        }}
    """


def ghost_button_style() -> str:
    """Tertiary actions: Restore Defaults, link-like buttons."""
    return f"""
        QPushButton {{
            background-color: transparent;
            border: none;
            color: {Color.TEXT_MUTED};
            padding: {Spacing.SM}px {Spacing.MD}px;
        }}
        QPushButton:hover {{ color: {Color.PRIMARY}; }}
        QPushButton:pressed {{ color: {Color.PRIMARY_PRESSED}; }}
    """


def danger_button_style() -> str:
    """For Quit and other destructive actions."""
    return f"""
        QPushButton {{
            background-color: rgba(239, 68, 68, 0.12);
            border: 1px solid {Color.DANGER};
            color: {Color.DANGER};
            border-radius: {Size.BORDER_RADIUS_SM}px;
            padding: {Spacing.SM}px {Spacing.MD}px;
        }}
        QPushButton:hover {{
            background-color: rgba(239, 68, 68, 0.25);
            border-color: {Color.DANGER_HOVER};
            color: {Color.DANGER_HOVER};
        }}
    """


# ── Section layout helpers ────────────────────────────────────────────────────

def make_section(title: str, parent: QWidget = None) -> tuple[QWidget, QFormLayout]:
    """Return (container, form_layout). Caller adds rows via form_layout.addRow(label, widget).

    Standardized section: 14pt 600-weight title + form layout with 12px row gap.
    """
    container = QWidget(parent)
    vbox = QVBoxLayout(container)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(Spacing.XS)     # 4 — gap between section title and form

    title_label = QLabel(title)
    font = QFont(Font.FAMILY, Font.SECTION_HEADER[0])
    font.setWeight(QFont.Weight.DemiBold)
    title_label.setFont(font)
    title_label.setStyleSheet(f"color: {Color.TEXT_HEADING};")
    vbox.addWidget(title_label)

    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setSpacing(Spacing.SM)     # 8 — gap between fields
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    vbox.addLayout(form)

    return container, form


def make_toggle_row(label_text: str, toggle: QWidget, parent: QWidget = None) -> QWidget:
    """Build a horizontal row: [Toggle .... Label].

    Used for boolean settings where the toggle is the only control.
    Row height is constrained to ~32px per spec.
    """
    from PySide6.QtWidgets import QHBoxLayout
    container = QWidget(parent)
    container.setFixedHeight(32)
    h = QHBoxLayout(container)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(Spacing.SM)

    label = QLabel(label_text)
    label.setStyleSheet(f"color: {Color.TEXT_BODY};")
    h.addWidget(toggle)
    h.addWidget(label)
    h.addStretch()
    return container


def section_separator_spacing() -> int:
    """The vertical gap between two sections in a tab."""
    return Spacing.SECTION  # 20px (per UI correction spec)


# ── Redesigned main-window helpers ───────────────────────────────────────────


def section_panel_style() -> str:
    """Subtle section container style."""
    return f"""
        QFrame#SectionPanel {{
            background-color: rgba(15, 30, 46, 0.82);
            border: 1px solid {Color.BORDER};
            border-radius: {Size.BORDER_RADIUS_LG}px;
        }}
    """


def compact_status_bar_style() -> str:
    """Single compact status bar container style."""
    return f"""
        QFrame#CompactStatusBar {{
            background-color: rgba(15, 30, 46, 0.82);
            border: 1px solid {Color.BORDER_SUBTLE};
            border-radius: {Size.BORDER_RADIUS_LG}px;
        }}
    """


def primary_record_button_style(state: str = "idle") -> str:
    """Primary Start Recording button style with state variants."""
    if state == "recording":
        bg, bg_hover, bg_pressed = Color.DANGER, Color.DANGER_HOVER, Color.DANGER_HOVER
        border = "rgba(248, 113, 113, 0.42)"
    elif state == "processing":
        bg, bg_hover, bg_pressed = Color.PANEL_ELEVATED, Color.PANEL_HOVER, Color.BORDER
        border = Color.BORDER_SUBTLE
    elif state == "disabled":
        bg, bg_hover, bg_pressed = Color.PANEL_ELEVATED, Color.PANEL_ELEVATED, Color.PANEL_ELEVATED
        border = Color.BORDER
    else:
        bg, bg_hover, bg_pressed = Color.PRIMARY, Color.PRIMARY_HOVER, Color.PRIMARY_PRESSED
        border = "rgba(96, 165, 250, 0.28)"
    return f"""
        QPushButton {{
            background-color: qlineargradient(
                x1: 0, y1: 0, x2: 1, y2: 1,
                stop: 0 {bg},
                stop: 1 {bg_pressed}
            );
            color: {Color.TEXT_PRIMARY};
            font-size: {Font.SECTION_HEADER[0]}pt;
            font-weight: bold;
            border: 1px solid {border};
            border-radius: {Size.BORDER_RADIUS_LG}px;
            min-height: {Size.BUTTON_HEIGHT_PRIMARY}px;
            padding: 0 {Spacing.LG}px;
        }}
        QPushButton:hover {{ background-color: {bg_hover}; }}
        QPushButton:pressed {{ background-color: {bg_pressed}; }}
        QPushButton:disabled {{
            background-color: {Color.PANEL_ELEVATED};
            color: {Color.TEXT_DISABLED};
        }}
    """


def make_bounded_content(
    parent: QWidget = None,
    max_width: int = Size.SETTING_ROW_MAX_WIDTH,
) -> tuple[QWidget, QVBoxLayout, QHBoxLayout]:
    """Create a centered bounded content area inside a stretch row."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)

    content = QWidget(parent)
    content.setObjectName("SectionContent")
    content.setMaximumWidth(max_width)
    content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(Spacing.MD)

    row.addStretch()
    row.addWidget(content, 100)
    row.addStretch()
    return content, content_layout, row


def make_separator(parent: QWidget = None) -> QFrame:
    """Subtle horizontal separator between rows."""
    separator = QFrame(parent)
    separator.setObjectName("SettingSeparator")
    separator.setFrameShape(QFrame.Shape.HLine)
    separator.setFrameShadow(QFrame.Shadow.Plain)
    separator.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    separator.setFixedHeight(1)
    separator.setStyleSheet(f"color: {Color.BORDER}; background: transparent;")
    return separator


def subtle_danger_button_style() -> str:
    """Low-emphasis Quit button style."""
    return f"""
        QPushButton {{
            background-color: transparent;
            border: 1px solid rgba(239, 68, 68, 0.48);
            border-radius: {Size.BORDER_RADIUS_SM}px;
            color: {Color.DANGER};
            padding: {Spacing.XS}px {Spacing.MD}px;
        }}
        QPushButton:hover {{
            background-color: rgba(239, 68, 68, 0.12);
            border-color: {Color.DANGER};
            color: {Color.DANGER_HOVER};
        }}
        QPushButton:pressed {{ background-color: rgba(239, 68, 68, 0.18); }}
    """


def make_setting_row(
    label_text: str,
    control: QWidget,
    parent: QWidget = None,
    icon_name: str | None = None,
    control_left: bool = False,
    stacked: bool = False,
    show_separator: bool = True,
) -> QWidget:
    """Return a settings row for use inside a bounded section content column."""
    del control_left  # Kept for source compatibility with older call sites.
    container = QWidget(parent)
    container.setObjectName("SettingRow")
    row_height = Size.SETTING_ROW_STACKED_HEIGHT if stacked else Size.SETTING_ROW_HEIGHT
    separator_height = Spacing.SM + 1 if show_separator else 0
    container.setFixedHeight(row_height + separator_height)
    container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    outer = QVBoxLayout(container)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(Spacing.SM)

    row_inner = QWidget(container)
    row_inner.setObjectName("SettingRowInner")
    row_inner.setFixedHeight(row_height)
    row_inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    label = QLabel(label_text)
    label.setStyleSheet(f"color: {Color.TEXT_HEADING};")

    if stacked:
        row = QVBoxLayout(row_inner)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(Spacing.SM)
        if icon_name:
            label_line = QHBoxLayout()
            label_line.setContentsMargins(0, 0, 0, 0)
            label_line.setSpacing(Spacing.SM)
            icon = QLabel()
            icon_size = 20
            icon.setPixmap(load_icon(icon_name).pixmap(icon_size, icon_size))
            icon.setFixedSize(icon_size, icon_size)
            label_line.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
            label_line.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
            label_line.addStretch()
            row.addLayout(label_line)
        else:
            row.addWidget(label, 0, Qt.AlignmentFlag.AlignLeft)
        control.setMinimumHeight(Size.INPUT_HEIGHT)
        row.addWidget(control)
    else:
        row = QHBoxLayout(row_inner)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(Spacing.SM)
        if icon_name:
            icon = QLabel()
            icon_size = 20
            icon.setPixmap(load_icon(icon_name).pixmap(icon_size, icon_size))
            icon.setFixedSize(icon_size, icon_size)
            row.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch()
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)

    outer.addWidget(row_inner)

    if show_separator:
        outer.addWidget(make_separator(container))

    return container


def make_section_panel(
    title: str,
    parent: QWidget = None,
    icon_name: str | None = None,
) -> tuple[QFrame, QVBoxLayout]:
    """Return (frame, content_layout) for a titled section with subtle border."""
    frame = QFrame(parent)
    frame.setObjectName("SectionPanel")
    frame.setStyleSheet(section_panel_style())
    outer = QVBoxLayout(frame)
    outer.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
    outer.setSpacing(Spacing.MD)
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(Spacing.SM)
    if icon_name:
        icon = QLabel()
        icon_size = 20
        icon.setPixmap(load_icon(icon_name).pixmap(icon_size, icon_size))
        icon.setFixedSize(icon_size, icon_size)
        header.addWidget(icon)
    title_label = QLabel(title)
    font = QFont(Font.FAMILY, Font.SECTION_HEADER[0])
    font.setWeight(QFont.Weight.DemiBold)
    title_label.setFont(font)
    title_label.setStyleSheet(f"color: {Color.TEXT_HEADING};")
    header.addWidget(title_label)
    header.addStretch()
    outer.addLayout(header)
    _, content, content_row = make_bounded_content(frame)
    outer.addLayout(content_row)
    return frame, content


def make_action_row(
    label_text: str,
    trailing_text: str = "›",
    parent: QWidget = None,
    icon_name: str | None = None,
) -> QWidget:
    """Return a clickable-looking row with label on left and trailing indicator on right.

    The returned widget exposes a ``clicked`` Signal via its ``clicked`` attribute
    and a ``setText(label)`` method for updating the label at runtime.
    """
    from PySide6.QtCore import Signal as _Signal
    from PySide6.QtWidgets import QHBoxLayout

    class _ActionRow(QWidget):
        clicked = _Signal()

        def __init__(self, label: str, trailing: str, p: QWidget) -> None:
            super().__init__(p)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFixedHeight(36)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setObjectName("ActionRow")
            self.setStyleSheet(f"""
                QWidget#ActionRow {{
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: {Size.BORDER_RADIUS_SM}px;
                }}
                QWidget#ActionRow:hover {{
                    background-color: rgba(27, 49, 71, 0.62);
                    border-color: {Color.BORDER_SUBTLE};
                }}
            """)
            h = QHBoxLayout(self)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(Spacing.SM)
            if icon_name:
                self._icon = QLabel()
                icon_size = 20
                self._icon.setPixmap(load_icon(icon_name).pixmap(icon_size, icon_size))
                self._icon.setFixedSize(icon_size, icon_size)
                h.addWidget(self._icon)
            self._lbl = QLabel(label)
            self._lbl.setStyleSheet(f"color: {Color.TEXT_BODY}; background: transparent;")
            self._trail = QLabel(trailing)
            trail_font = QFont(Font.FAMILY, Font.SECTION_HEADER[0])
            trail_font.setWeight(QFont.Weight.DemiBold)
            self._trail.setFont(trail_font)
            self._trail.setStyleSheet(f"color: {Color.TEXT_BODY}; background: transparent;")
            h.addWidget(self._lbl)
            h.addStretch()
            h.addWidget(self._trail)

        def setText(self, text: str) -> None:  # noqa: N802
            self._lbl.setText(text)

        def mousePressEvent(self, event) -> None:  # noqa: N802
            if event.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit()
                event.accept()
                return
            super().mousePressEvent(event)

        def keyPressEvent(self, event) -> None:  # noqa: N802
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                self.clicked.emit()
                event.accept()
                return
            super().keyPressEvent(event)

        def enterEvent(self, event) -> None:  # noqa: N802
            self._lbl.setStyleSheet(f"color: {Color.TEXT_PRIMARY}; background: transparent;")
            self._trail.setStyleSheet(f"color: {Color.PRIMARY}; background: transparent;")
            super().enterEvent(event)

        def leaveEvent(self, event) -> None:  # noqa: N802
            self._lbl.setStyleSheet(f"color: {Color.TEXT_BODY}; background: transparent;")
            self._trail.setStyleSheet(f"color: {Color.TEXT_BODY}; background: transparent;")
            super().leaveEvent(event)

    return _ActionRow(label_text, trailing_text, parent)
