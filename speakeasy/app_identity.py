"""Application identity helpers for Windows shell integration."""

from __future__ import annotations

from pathlib import Path


APP_USER_MODEL_ID = "SpeakEasyAI.Granite.SpeechToText"


def app_icon_path() -> Path:
    """Return the packaged app icon path for source and frozen builds."""
    return Path(__file__).resolve().parent / "assets" / "app.ico"
