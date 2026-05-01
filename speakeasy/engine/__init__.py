"""Engine registry — registers the Cohere Transcribe speech engine."""

from __future__ import annotations

import logging
import os
from typing import Dict, Type

log = logging.getLogger(__name__)

ENGINES: Dict[str, Type] = {}

try:
    from .cohere_transcribe import CohereTranscribeEngine
    ENGINES["cohere"] = CohereTranscribeEngine
except ImportError:
    log.debug("Cohere engine unavailable (transformers not installed)")


# ── Model-file detection ─────────────────────────────────────────────────────


def _model_files_exist(engine_name: str, model_path: str) -> bool:
    """Return True if the model files for *engine_name* are present on disk."""
    engine_dir = os.path.join(model_path, engine_name)
    return os.path.isdir(engine_dir) and os.path.isfile(
        os.path.join(engine_dir, "config.json")
    )


def get_available_engines(model_path: str) -> list:
    """Return engine names whose dependencies AND model files are installed."""
    return [
        name for name in ENGINES if _model_files_exist(name, model_path)
    ]
