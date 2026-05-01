"""Shared fixtures for the SpeakEasy AI test suite.

Every fixture that touches hardware (GPU, mic, OS hotkeys, clipboard) is
mocked so the suite runs headlessly in CI without special resources.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Force Qt offscreen rendering for headless CI
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ── QApplication for xdist workers ────────────────────────────────────────────
# pytest-qt's qapp fixture is session-scoped but only activates when a test
# explicitly requests it (or qtbot).  Fixtures that construct widgets directly
# (e.g. LogsWidget()) need a QApplication to already exist.  Creating one
# eagerly in every xdist worker prevents sporadic crashes.

@pytest.fixture(scope="session", autouse=True)
def _ensure_qapp():
    """Guarantee a QApplication exists for the entire worker session."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        yield
        return
    app = QApplication.instance() or QApplication([])
    yield app


# ── Settings isolation ────────────────────────────────────────────────────────

@pytest.fixture
def temp_settings_dir(tmp_path, monkeypatch):
    """Redirect Settings persistence to a temp directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    presets_dir = config_dir / "presets"
    presets_dir.mkdir()
    monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_DIR", config_dir)
    monkeypatch.setattr("speakeasy.config.DEFAULT_CONFIG_FILE", config_dir / "settings.json")
    monkeypatch.setattr("speakeasy.config.DEFAULT_PRESETS_DIR", presets_dir)
    return config_dir


@pytest.fixture
def fresh_settings(temp_settings_dir):
    """A clean Settings instance with default values, isolated to temp dir."""
    from speakeasy.config import Settings
    return Settings()


# ── Hardware isolation for MainWindow tests ──────────────────────────────────

class _FakeAudioRecorder:
    """No-op recorder used by MainWindow tests so xdist never opens a real mic."""

    def __init__(
        self,
        sample_rate=16000,
        silence_threshold=0.0015,
        silence_margin_ms=500,
        device=None,
    ):
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold
        self.silence_margin = int(sample_rate * silence_margin_ms / 1000)
        self.device = device
        self._recording = False
        self._audio = np.zeros(sample_rate, dtype=np.float32)

    def open_stream(self) -> None:
        pass

    def close_stream(self) -> None:
        pass

    def stream_is_alive(self, timeout: float = 0.5) -> bool:
        return True

    def recover_stream(self) -> bool:
        return True

    def start_recording(self) -> None:
        self._recording = True

    def stop_recording(self) -> None:
        self._recording = False

    def get_raw_audio(self):
        self._recording = False
        return self._audio.copy()

    def trim_silence(self, audio):
        return audio, 0.0


@pytest.fixture(autouse=True)
def _mock_main_window_audio(monkeypatch):
    """Patch only MainWindow's recorder binding; audio.py unit tests stay real."""
    monkeypatch.setattr("speakeasy.main_window.AudioRecorder", _FakeAudioRecorder)
