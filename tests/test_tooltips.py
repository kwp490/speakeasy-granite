"""Tooltip / accessibility coverage for user-facing controls (Phase 6 §10).

Every interactive control declared on the settings, AI-providers, AI-writing-
profiles and history surfaces must carry a non-empty tooltip so the UI is
self-explanatory and screen-reader friendly.  We scan each widget's declared
attributes (``__dict__``) rather than ``findChildren`` so Qt's internal step /
edit children (which legitimately have no tooltip) do not produce false
failures.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
)

from speakeasy.ai_providers_widget import AIProvidersWidget  # noqa: E402
from speakeasy.config import Settings  # noqa: E402
from speakeasy.history_widget import HistoryWidget  # noqa: E402
from speakeasy.main_window import ToggleSwitch  # noqa: E402
from speakeasy.pro_mode_widget import ProModeWidget  # noqa: E402
from speakeasy.settings_dialog import AdvancedSettingsWidget, SettingsWidget  # noqa: E402
from speakeasy.ui.tooltips import TOOLTIPS, apply_tooltip  # noqa: E402

# Interactive control types that must always carry a tooltip.
_INTERACTIVE = (
    QComboBox,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QRadioButton,
    QPushButton,
    ToggleSwitch,
)


def _missing_tooltips(widget) -> list[str]:
    """Return attribute names of declared interactive controls lacking a tooltip."""
    missing = []
    for name, value in vars(widget).items():
        if isinstance(value, _INTERACTIVE):
            if not (value.toolTip() or "").strip():
                missing.append(name)
    return missing


def _make_settings() -> Settings:
    return Settings()


def test_settings_widget_controls_have_tooltips():
    w = SettingsWidget(_make_settings())
    assert _missing_tooltips(w) == [], f"controls without tooltips: {_missing_tooltips(w)}"


def test_advanced_settings_widget_controls_have_tooltips():
    w = AdvancedSettingsWidget(_make_settings())
    assert _missing_tooltips(w) == [], f"controls without tooltips: {_missing_tooltips(w)}"


def test_ai_providers_widget_controls_have_tooltips():
    w = AIProvidersWidget(_make_settings())
    assert _missing_tooltips(w) == [], f"controls without tooltips: {_missing_tooltips(w)}"


def test_pro_mode_widget_controls_have_tooltips():
    w = ProModeWidget(_make_settings())
    assert _missing_tooltips(w) == [], f"controls without tooltips: {_missing_tooltips(w)}"


def test_history_widget_controls_have_tooltips():
    w = HistoryWidget()
    assert _missing_tooltips(w) == [], f"controls without tooltips: {_missing_tooltips(w)}"


# ── Registry contract ────────────────────────────────────────────────────────


def test_registry_values_non_empty():
    assert TOOLTIPS, "registry must not be empty"
    for key, text in TOOLTIPS.items():
        assert text and text.strip(), f"empty tooltip for {key!r}"


def test_apply_tooltip_sets_tooltip_and_accessible_description():
    w = QPushButton()
    apply_tooltip(w, "settings.apply")
    assert w.toolTip() == TOOLTIPS["settings.apply"]
    assert w.accessibleDescription() == TOOLTIPS["settings.apply"]


def test_apply_tooltip_unknown_key_raises():
    w = QPushButton()
    with pytest.raises(KeyError):
        apply_tooltip(w, "does.not.exist")
