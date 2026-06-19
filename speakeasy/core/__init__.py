"""SpeakEasy core layer — transport-agnostic engine contract.

Modules in this package MUST NOT import torch, transformers, librosa,
accelerate, or PySide6 at module scope.  They define the data types and
protocols that the UI and engine layers agree on, so the UI process can
import them in an interpreter without the heavy ML stack installed.
"""

from __future__ import annotations

from .contract import (
    CONTRACT_VERSION,
    EngineCapabilities,
    EngineDescriptor,
    EngineStats,
    HealthReport,
    LoadReport,
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptionService,
)
from .errors import (
    DeviceUnavailable,
    EngineError,
    InferenceTimeout,
    ModelAuthRequired,
    ModelFilesMissing,
    ModelNotConfigured,
    RemoteAuthFailed,
    RemoteUnreachable,
    RemoteVersionMismatch,
)
from .model_source import (
    LocalDirSource,
    ManagedSource,
    ModelSource,
    RemoteSource,
    classify_path,
    parse,
    to_dict,
)

__all__ = [
    "CONTRACT_VERSION",
    "EngineCapabilities",
    "EngineDescriptor",
    "EngineStats",
    "HealthReport",
    "LoadReport",
    "TranscriptionOptions",
    "TranscriptionResult",
    "TranscriptionService",
    "EngineError",
    "ModelNotConfigured",
    "ModelFilesMissing",
    "ModelAuthRequired",
    "DeviceUnavailable",
    "InferenceTimeout",
    "RemoteUnreachable",
    "RemoteAuthFailed",
    "RemoteVersionMismatch",
    "ModelSource",
    "ManagedSource",
    "LocalDirSource",
    "RemoteSource",
    "parse",
    "to_dict",
    "classify_path",
]
