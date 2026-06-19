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
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from ._build_variant import VARIANT
from .pro_preset import DEFAULT_PRO_MODEL, PRO_MODE_MODEL_OPTIONS

log = logging.getLogger(__name__)

_REMOVED_TRANSCRIPTION_PREVIEW_SETTINGS = {
    # Removed live-preview settings from earlier dictation experiments.
    "streaming_partials_enabled",
    "live_transcription_enabled",
    "live_preview_enabled",
    "streaming_enabled",
    "incremental_decoding_enabled",
    "partial_transcription_enabled",
    "liveTranscription",
    "livePreview",
    "streamingMode",
    "partialTranscript",
    "previewTranscript",
}

_MISSING = object()

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
    # ``model_path`` is the resolved *local* directory the engine loads from.  It
    # is kept as a legacy mirror of ``model_source`` so a downgrade to 0.14.x
    # still boots; ``model_source`` (the discriminated schema in
    # ``core.model_source``) is the forward-looking source of truth.
    model_path: str = DEFAULT_MODELS_DIR
    model_source: dict = field(default_factory=dict)
    device: str = "cpu" if VARIANT == "cpu" else "cuda"
    language: str = "en"
    speech_task: str = "transcribe"
    translation_target_language: str = "English"
    keyword_bias: str = ""
    inference_timeout: int = 30
    punctuation: bool = True
    formatting_style: str = "sentence_case"

    # ── Dictation UX ─────────────────────────────────────────────────────────
    auto_copy: bool = True
    auto_paste: bool = True
    hotkeys_enabled: bool = True
    hotkey_start: str = "ctrl+alt+p"
    hotkey_quit: str = "ctrl+alt+q"
    clear_logs_on_exit: bool = True

    # ── Audio ─────────────────────────────────────────────────────────────────
    mic_device_index: int = -1           # -1 = system default
    sample_rate: int = 16000             # recording only — always resampled to 16 kHz for engines
    silence_threshold: float = 0.0015
    silence_margin_ms: int = 500

    # ── AI Writing Profiles + Providers ──────────────────────────────────────
    professional_mode: bool = False
    pro_active_preset: str = "General Professional"
    pro_default_model: str = DEFAULT_PRO_MODEL
    store_api_key: bool = False
    pro_disclosure_accepted: bool = False  # True once user acknowledges data-privacy notice
    provider: str = "openai"               # AI Providers tab: openai | local_granite (future)

    # ── Remote ASR ────────────────────────────────────────────────────────────
    remote_disclosure_accepted: bool = False  # True once user accepts the remote-audio notice

    # ── Developer Panel ──────────────────────────────────────────────────────
    dev_panel_open: bool = False
    dev_panel_active_tab: str = "settings"   # one of: settings, pro, diagnostics, history, advanced
    dev_panel_width: int = 629
    dev_panel_height: int = 880
    dev_panel_snapped: bool = True           # True = follows main window's right edge
    hotkey_dev_panel: str = "ctrl+alt+d"     # user-configurable in Hotkeys section

    # Transient (NOT persisted — plain class attribute, not a dataclass field):
    # set by validate() when a custom model location is configured but currently
    # unreachable (offline UNC share / disconnected removable drive).  The UI
    # surfaces this as a "needs attention" badge instead of erasing the setting.
    model_location_needs_attention = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    _VALID_ENGINES = {"granite"}
    _VALID_DEVICES = {"cpu"} if VARIANT == "cpu" else {"cuda", "cpu"}
    _VALID_SPEECH_TASKS = {"transcribe", "translate"}
    _VALID_LANGUAGES = {"auto", "en", "fr", "de", "es", "pt", "ja"}
    _VALID_TRANSLATION_TARGETS = {
        "English", "French", "German", "Spanish", "Japanese", "Italian", "Mandarin"
    }
    _VALID_FORMATTING_STYLES = {"plain_text", "sentence_case", "preserve_spoken_wording"}

    def validate(self) -> None:
        """Clamp/correct invalid field values to safe defaults."""
        if self.engine not in self._VALID_ENGINES:
            log.warning("Unknown engine '%s'; falling back to 'granite'", self.engine)
            self.engine = "granite"
        if self.speech_task not in self._VALID_SPEECH_TASKS:
            log.warning("Unknown speech_task '%s'; falling back to 'transcribe'", self.speech_task)
            self.speech_task = "transcribe"
        if self.language not in self._VALID_LANGUAGES:
            log.warning("Unknown language '%s'; falling back to 'en'", self.language)
            self.language = "en"
        if self.translation_target_language not in self._VALID_TRANSLATION_TARGETS:
            self.translation_target_language = "English"
        if self.formatting_style not in self._VALID_FORMATTING_STYLES:
            log.warning(
                "Unknown formatting_style '%s'; falling back to 'sentence_case'",
                self.formatting_style,
            )
            self.formatting_style = "sentence_case"
        self.keyword_bias = str(self.keyword_bias or "").strip()
        self._resolve_model_source()
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
        # Phase 6 merged the Developer Panel down to five tabs.  Remap legacy
        # tab keys saved by older builds: AI Providers folded into AI Writing
        # Profiles; Metrics + Logs merged into Diagnostics.
        _tab_remap = {"providers": "pro", "realtime": "diagnostics", "logs": "diagnostics"}
        self.dev_panel_active_tab = _tab_remap.get(
            self.dev_panel_active_tab, self.dev_panel_active_tab
        )
        valid_tabs = {"settings", "pro", "diagnostics", "history", "advanced"}
        if self.provider not in {"openai", "local_granite"}:
            self.provider = "openai"
        if self.dev_panel_active_tab not in valid_tabs:
            self.dev_panel_active_tab = "settings"
        if self.pro_default_model not in PRO_MODE_MODEL_OPTIONS:
            self.pro_default_model = DEFAULT_PRO_MODEL
        if self.dev_panel_width < 540:
            self.dev_panel_width = 629
        if self.dev_panel_width > 800:
            self.dev_panel_width = 800
        if self.dev_panel_height < 400:
            self.dev_panel_height = 880

    def _resolve_model_source(self) -> None:
        """Normalize ``model_source`` and keep the legacy ``model_path`` mirror in sync.

        Migration rules (also covers a 0.14.x ``settings.json`` that only has
        ``model_path``):

        * No / empty ``model_source`` ⇒ derive it from ``model_path`` —
          ``managed`` when it equals the default models dir, otherwise
          ``local_dir`` (even if the path is currently unreachable).
        * An invalid ``model_source`` falls back to ``managed``.

        Unlike the previous behavior, a custom directory that is offline (an
        unplugged removable drive or an offline UNC share) is **never** reset to
        the default — the setting is preserved and ``model_location_needs_attention``
        is raised so the UI can show a badge.
        """
        from .core import model_source as ms

        raw = self.model_source if isinstance(self.model_source, dict) else {}
        if not raw or "type" not in raw:
            if self.model_path and self.model_path != DEFAULT_MODELS_DIR:
                src: ms.ModelSource = ms.LocalDirSource(path=self.model_path)
            else:
                src = ms.ManagedSource()
        else:
            try:
                src = ms.parse(raw)
            except (ValueError, TypeError):
                log.warning(
                    "Invalid model_source %r; falling back to managed location", raw
                )
                src = ms.ManagedSource()

        self.model_location_needs_attention = False
        if isinstance(src, ms.LocalDirSource):
            path = src.path or DEFAULT_MODELS_DIR
            self.model_path = path
            src = ms.LocalDirSource(path=path)
            if path != DEFAULT_MODELS_DIR and not os.path.isdir(path):
                self.model_location_needs_attention = True
                log.info(
                    "Model location '%s' is not currently reachable; "
                    "the saved setting was kept",
                    path,
                )
        else:
            # Managed and remote sources both mirror the managed default so a
            # downgrade to 0.14.x still finds a usable local path.
            self.model_path = DEFAULT_MODELS_DIR

        self.model_source = ms.to_dict(src)

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
            if isinstance(data, dict):
                # Older settings files may still contain abandoned live-preview
                # toggles. Drop them and rewrite the file so later saves stay clean.
                removed = sorted(_REMOVED_TRANSCRIPTION_PREVIEW_SETTINGS.intersection(data))
                if removed:
                    data = {k: v for k, v in data.items() if k not in removed}
                    log.debug(
                        "Removed deprecated transcription preview settings from %s: %s",
                        path,
                        ", ".join(removed),
                    )
                    try:
                        with open(path, "w", encoding="utf-8") as fh:
                            json.dump(data, fh, indent=2)
                    except Exception:
                        log.debug(
                            "Could not rewrite settings file after removing deprecated keys",
                            exc_info=True,
                        )
                # Professional Mode used to persist a separate enabled flag and
                # active_profile_id. Convert those fields to the preset-based model.
                if "professional_mode_enabled" in data and "professional_mode" not in data:
                    data["professional_mode"] = bool(data["professional_mode_enabled"])

                active_profile_id = data.get("active_profile_id", _MISSING)
                if active_profile_id is not _MISSING:
                    if active_profile_id in (None, "", "None"):
                        data["professional_mode"] = False
                        data.setdefault("pro_active_preset", cls.pro_active_preset)
                    else:
                        data["professional_mode"] = True
                        data["pro_active_preset"] = str(active_profile_id)
            known = {f.name for f in fields(cls)}
            instance = cls(**{k: v for k, v in data.items() if k in known})
            instance.validate()
            return instance
        except Exception:
            log.warning("Failed to load settings; using defaults", exc_info=True)
            return cls()
