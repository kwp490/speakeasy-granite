"""Legacy engine package shim.

The heavy ML imports now live behind :mod:`speakeasy.engines.registry`, whose
factories defer ``torch``/``transformers`` to call time.  The Granite engine
*module* itself is also torch-free at import time (those packages are imported
lazily inside its methods), so re-exporting the class here no longer pulls torch
into importers.  New code should prefer :mod:`speakeasy.engines.registry`; this
module preserves the historical ``ENGINES`` / ``get_available_engines`` /
``_model_files_exist`` surface for existing callers and tests.
"""

from __future__ import annotations

import logging
from typing import Dict, Type

log = logging.getLogger(__name__)

ENGINES: Dict[str, Type] = {}

try:
    from .granite_transcribe import GraniteTranscribeEngine

    ENGINES["granite"] = GraniteTranscribeEngine
except ImportError:
    log.debug("Granite engine class unavailable")


# ── Model-file detection ─────────────────────────────────────────────────────


def _model_files_exist(engine_name: str, model_path: str) -> bool:
    """Return True if the model files for *engine_name* are present on disk."""
    from ..model_downloader import model_ready

    return model_ready(engine_name, model_path)


def get_available_engines(model_path: str) -> list:
    """Return engine names whose model files are installed on disk.

    Mirrors the historical behaviour (model-file presence only).  For a
    dependency-aware view use
    :func:`speakeasy.engines.registry.available_engines`.
    """
    return [name for name in ENGINES if _model_files_exist(name, model_path)]


__all__ = ["ENGINES", "get_available_engines"]
