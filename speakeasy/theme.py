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
from PySide6.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget


ICON_DIR = Path(__file__).parent / "assets" / "icons"


# ── Color tokens ──────────────────────────────────────────────────────────────

class Color:
    # Surfaces
    BACKGROUND = "#0F172A"       # app background (slate-900)
    PANEL = "#111827"            # cards, group boxes (gray-900)
    PANEL_ELEVATED = "#1F2937"   # hover/active surfaces (gray-800)
    PANEL_HOVER = "#252F3E"      # clickable status cards
    BORDER = "#1F2937"           # default border
    BORDER_SUBTLE = "#374151"    # tab borders, subtle dividers
    INPUT_BG = "#1F2937"         # text inputs, dropdowns (gray-800, per spec)

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
    TEXT_PRIMARY = "#FFFFFF"     # app title, emphasis
    TEXT_HEADING = "#E5E7EB"     # section headers (gray-200)
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
    BUTTON_HEIGHT_PRIMARY = 48     # Start Recording, prominent CTAs
    GEAR_BUTTON = 60               # square gear button to right of record
    INPUT_HEIGHT = 36
    TAB_HEIGHT = 40
    PROGRESS_BAR_HEIGHT = 6        # thin bars in Realtime Data
    STATUS_DOT = 8                 # colored dots in status row
    STATUS_ICON_CARD = 24
    STATUS_ICON_PILL = 18
    STATUS_CARD_MIN_HEIGHT = 64
    STATUS_PILL_MIN_HEIGHT = 32
    STATUS_LAYOUT_THRESHOLD = 640
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
        QMainWindow, QWidget {{
            background-color: {Color.BACKGROUND};
            color: {Color.TEXT_BODY};
            font-family: '{Font.FAMILY}', sans-serif;
            font-size: {Font.BODY[0]}pt;
        }}

        QGroupBox {{
            background-color: {Color.PANEL};
            border: 1px solid {Color.BORDER};
            border-radius: {Size.BORDER_RADIUS_MD}px;
            margin-top: {Spacing.MD}px;
            padding: {Spacing.LG}px;
            color: {Color.TEXT_HEADING};
            font-weight: 600;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: {Spacing.MD}px;
            padding: 0 {Spacing.SM}px;
        }}

        QLabel {{ background: transparent; }}

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
            background-color: {Color.PRIMARY};
            color: {Color.TEXT_PRIMARY};
            font-size: {Font.SECTION_HEADER[0]}pt;
            font-weight: bold;
            border: none;
            border-radius: {Size.BORDER_RADIUS_LG}px;
            min-height: {Size.BUTTON_HEIGHT_PRIMARY}px;
        }}
        QPushButton:hover {{ background-color: {Color.PRIMARY_HOVER}; }}
        QPushButton:pressed {{ background-color: {Color.PRIMARY_PRESSED}; }}
        QPushButton:disabled {{
            background-color: {Color.PANEL_ELEVATED};
            color: {Color.TEXT_DISABLED};
        }}
    """


def gear_button_style() -> str:
    """The square gear button next to Start Recording."""
    return f"""
        QPushButton {{
            background-color: {Color.PANEL_ELEVATED};
            color: {Color.TEXT_BODY};
            font-size: 22px;
            border: 1px solid {Color.BORDER_SUBTLE};
            border-radius: {Size.BORDER_RADIUS_SM}px;
        }}
        QPushButton:hover {{
            background-color: {Color.BORDER_SUBTLE};
            border-color: {Color.PRIMARY};
            color: {Color.TEXT_PRIMARY};
        }}
        QPushButton:pressed {{ background-color: {Color.BORDER}; }}
        QPushButton:checked {{
            background-color: {Color.PRIMARY};
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
