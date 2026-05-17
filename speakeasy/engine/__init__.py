"""Engine registry — registers the IBM Granite speech engine."""

from __future__ import annotations

import logging
from typing import Dict, Type

log = logging.getLogger(__name__)

ENGINES: Dict[str, Type] = {}

try:
    from .granite_transcribe import GraniteTranscribeEngine
    ENGINES["granite"] = GraniteTranscribeEngine
except ImportError:
    log.debug("Granite engine unavailable (transformers not installed)")


# ── Model-file detection ─────────────────────────────────────────────────────


def _model_files_exist(engine_name: str, model_path: str) -> bool:
    """Return True if the model files for *engine_name* are present on disk."""
    from speakeasy.model_downloader import model_ready
    return model_ready(engine_name, model_path)


def get_available_engines(model_path: str) -> list:
    """Return engine names whose dependencies AND model files are installed."""
    return [
        name for name in ENGINES if _model_files_exist(name, model_path)
    ]
