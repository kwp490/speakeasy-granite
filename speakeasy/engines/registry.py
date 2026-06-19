"""Engine registry — maps engine names to lazy factories.

Importing this module must **not** import torch/transformers/librosa.  Each
:class:`EngineDescriptor` carries a ``factory`` that performs the heavy import
only when called, plus ``requires`` (the top-level modules the engine needs at
load time).  This keeps the UI process torch-free until a model is actually
loaded, while ``installed_engines()`` can answer "is this engine usable?" via
:func:`importlib.util.find_spec` without importing anything heavy.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Callable, Dict, List

from ..core.contract import TranscriptionService


@dataclass(frozen=True)
class EngineDescriptor:
    """A lazily-constructible engine.

    ``factory`` returns a duck-typed speech engine (the structural surface the
    :class:`~speakeasy.services.inprocess.InProcessEngineService` adapts).  It
    is only called when a model is loaded, so importing this module stays
    torch-free.
    """

    name: str
    factory: Callable[[], object]
    requires: tuple[str, ...] = ()


def _make_granite_engine() -> object:
    # Heavy import deferred to call time (engine thread), never at module scope.
    from ..engine.granite_transcribe import GraniteTranscribeEngine

    return GraniteTranscribeEngine()


ENGINE_DESCRIPTORS: Dict[str, EngineDescriptor] = {
    "granite": EngineDescriptor(
        name="granite",
        factory=_make_granite_engine,
        requires=("torch", "transformers", "torchaudio"),
    ),
}


def _is_importable(module: str) -> bool:
    """Return True if *module* can be imported, without importing it."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def installed_engines() -> List[str]:
    """Engine names whose Python dependencies are importable.

    Uses :func:`importlib.util.find_spec` only — no heavy import is performed.
    """
    return [
        name
        for name, desc in ENGINE_DESCRIPTORS.items()
        if all(_is_importable(mod) for mod in desc.requires)
    ]


def available_engines(model_path: str) -> List[str]:
    """Engine names whose dependencies **and** model files are present."""
    from ..model_downloader import model_ready

    return [
        name for name in installed_engines() if model_ready(name, model_path)
    ]


def create_engine(name: str) -> object:
    """Instantiate the raw duck-typed engine for *name* (heavy import here)."""
    try:
        descriptor = ENGINE_DESCRIPTORS[name]
    except KeyError:
        raise ValueError(f"Unknown engine: {name!r}") from None
    return descriptor.factory()


def create_service(name: str) -> TranscriptionService:
    """Build an in-process :class:`TranscriptionService` for *name*."""
    from ..services.inprocess import InProcessEngineService

    return InProcessEngineService(create_engine(name))
