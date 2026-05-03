r"""
Configuration persistence for SpeakEasy AI.

App binaries live under the install directory (default C:\Program Files\SpeakEasy AI Granite).
Mutable data (config, models, temp) lives under %ProgramData%\SpeakEasy AI Granite so
that Program Files binaries stay read-only.  Logs are stored per-user under
%LOCALAPPDATA%\SpeakEasy AI Granite\logs to prevent cross-user access on shared machines.
In dev/source mode (SPEAKEASY_HOME set), all data is kept under INSTALL_DIR for a
self-contained dev environment.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from ._build_variant import VARIANT

log = logging.getLogger(__name__)

INSTALL_DIR = Path(os.environ.get("SPEAKEASY_HOME", r"C:\Program Files\SpeakEasy AI Granite"))

# In dev mode (SPEAKEASY_HOME set) keep all mutable data under INSTALL_DIR so
# everything stays self-contained in dev-temp/.  In a production install
# (SPEAKEASY_HOME not set) mutable data goes to %ProgramData%\SpeakEasy AI Granite so
# the binaries in Program Files remain read-only and require no Defender exclusion.
_DATA_DIR = (
    INSTALL_DIR
    if "SPEAKEASY_HOME" in os.environ
    else Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "SpeakEasy AI Granite"
)

DEFAULT_CONFIG_DIR = _DATA_DIR / "config"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "settings.json"
DEFAULT_PRESETS_DIR = DEFAULT_CONFIG_DIR / "presets"
DEFAULT_MODELS_DIR = str(_DATA_DIR / "models")

# Logs go to a per-user directory (%LOCALAPPDATA%\SpeakEasy AI Granite\logs) in production
# to prevent cross-user log access on shared machines.  In dev mode (SPEAKEASY_HOME)
# logs stay under INSTALL_DIR for a self-contained dev environment.
DEFAULT_LOG_DIR = (
    _DATA_DIR / "logs"
    if "SPEAKEASY_HOME" in os.environ
    else Path(os.environ.get("LOCALAPPDATA", "")) / "SpeakEasy AI Granite" / "logs"
)


@dataclass
class Settings:
    """All user-configurable settings with sensible defaults."""

    # ── Model Engine ──────────────────────────────────────────────────────────
    engine: str = "granite"
    model_path: str = DEFAULT_MODELS_DIR
    device: str = "cpu" if VARIANT == "cpu" else "cuda"
    language: str = "en"
    speech_task: str = "transcribe"
    translation_target_language: str = "English"
    keyword_bias: str = ""
    inference_timeout: int = 30
    punctuation: bool = True

    # ── Dictation UX ─────────────────────────────────────────────────────────
    auto_copy: bool = True
    auto_paste: bool = True
    hotkeys_enabled: bool = True
    hotkey_start: str = "ctrl+alt+p"
    hotkey_quit: str = "ctrl+alt+q"
    clear_logs_on_exit: bool = True
    # When True, long recordings emit a "live draft" history entry that grows
    # chunk-by-chunk as the engine transcribes. Clipboard/paste still fires
    # once on the final stitched text. CPU builds render slower per chunk.
    streaming_partials_enabled: bool = True

    # ── Audio ─────────────────────────────────────────────────────────────────
    mic_device_index: int = -1           # -1 = system default
    sample_rate: int = 16000             # recording only — always resampled to 16 kHz for engines
    silence_threshold: float = 0.0015
    silence_margin_ms: int = 500

    # ── Professional Mode ─────────────────────────────────────────────────────
    professional_mode: bool = False
    pro_active_preset: str = "General Professional"
    store_api_key: bool = False
    pro_disclosure_accepted: bool = False  # True once user acknowledges data-privacy notice

    # ── Developer Panel ──────────────────────────────────────────────────────
    dev_panel_open: bool = False
    dev_panel_active_tab: str = "settings"   # one of: settings, realtime, logs, pro
    dev_panel_width: int = 629
    dev_panel_height: int = 1131
    dev_panel_snapped: bool = True           # True = follows main window's right edge
    hotkey_dev_panel: str = "ctrl+alt+d"     # user-configurable in Hotkeys section

    # ── Helpers ───────────────────────────────────────────────────────────────

    _VALID_ENGINES = {"granite"}
    _VALID_DEVICES = {"cpu"} if VARIANT == "cpu" else {"cuda", "cpu"}
    _VALID_SPEECH_TASKS = {"transcribe", "translate"}

    def validate(self) -> None:
        """Clamp/correct invalid field values to safe defaults."""
        if self.engine not in self._VALID_ENGINES:
            log.warning("Unknown engine '%s'; falling back to 'granite'", self.engine)
            self.engine = "granite"
        if self.speech_task not in self._VALID_SPEECH_TASKS:
            log.warning("Unknown speech_task '%s'; falling back to 'transcribe'", self.speech_task)
            self.speech_task = "transcribe"
        if not self.translation_target_language:
            self.translation_target_language = "English"
        self.keyword_bias = str(self.keyword_bias or "").strip()
        if self.model_path != DEFAULT_MODELS_DIR and not os.path.isdir(self.model_path):
            log.warning("model_path '%s' does not exist; resetting to default", self.model_path)
            self.model_path = DEFAULT_MODELS_DIR
        _default_device = "cpu" if VARIANT == "cpu" else "cuda"
        if self.device not in self._VALID_DEVICES:
            log.warning("Unknown device '%s'; falling back to '%s'", self.device, _default_device)
            self.device = _default_device
        if self.sample_rate < 8000 or self.sample_rate > 48000:
            log.warning("Invalid sample_rate %d; resetting to 16000", self.sample_rate)
            self.sample_rate = 16000
        if self.inference_timeout < 1:
            self.inference_timeout = 30
        if self.silence_threshold <= 0:
            self.silence_threshold = 0.0015
        valid_tabs = {"settings", "realtime", "logs", "pro", "history"}
        if self.dev_panel_active_tab not in valid_tabs:
            self.dev_panel_active_tab = "settings"
        if self.dev_panel_width < 540:
            self.dev_panel_width = 629
        if self.dev_panel_width > 800:
            self.dev_panel_width = 800
        if self.dev_panel_height < 400:
            self.dev_panel_height = 1131

    def save(self, path: Path | None = None) -> None:
        """Persist settings to JSON file."""
        path = path or DEFAULT_CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)
        log.info("Settings saved to %s", path)

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        """Load settings from JSON, falling back to defaults for missing keys."""
        path = path or DEFAULT_CONFIG_FILE
        if not path.exists():
            log.info("No settings file found; using defaults")
            return cls()
        try:
            with open(path, encoding="utf-8-sig") as fh:
                data = json.load(fh)
            known = {f.name for f in fields(cls)}
            instance = cls(**{k: v for k, v in data.items() if k in known})
            instance.validate()
            return instance
        except Exception:
            log.warning("Failed to load settings; using defaults", exc_info=True)
            return cls()
