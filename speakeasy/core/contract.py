"""The transport-agnostic transcription contract.

``TranscriptionService`` is a structural :class:`typing.Protocol`: any object
that provides these methods satisfies it, whether it wraps an in-process engine
or talks to a remote server.  All data types here are plain frozen dataclasses
so they round-trip cleanly to JSON for the wire protocol.

This module must remain free of torch/transformers/librosa/Qt imports.  The
only third-party import is numpy, which the UI already depends on for audio
buffers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from .model_source import ModelSource

# Wire-protocol version, reported by ``/v1/health`` and checked by remote
# clients.  Bump only on incompatible changes to the contract data types.
CONTRACT_VERSION = 1


@dataclass(frozen=True)
class EngineDescriptor:
    """Identity of a transcription service."""

    name: str
    version: str
    is_remote: bool = False


@dataclass(frozen=True)
class EngineCapabilities:
    """Machine-readable description of what an engine can do.

    The UI populates its combos from this once a model is loaded, instead of
    hard-coding language/translation/formatting lists.
    """

    languages: tuple[str, ...]
    supports_translation: bool
    translation_targets: tuple[str, ...]
    supports_keyword_bias: bool
    supports_timestamps: bool
    supports_streaming: bool
    formatting_styles: tuple[str, ...]
    devices: tuple[str, ...]
    max_clip_seconds: float
    is_remote: bool


@dataclass(frozen=True)
class TranscriptionOptions:
    """Per-request transcription parameters.

    Absorbs the former ``configure_prompt_options`` side-channel so options
    travel *with* each request rather than mutating engine state.
    """

    task: str = "transcribe"          # "transcribe" | "translate"
    language: str = "en"
    translation_target: str = "English"
    keyword_bias: str = ""
    punctuation: bool = True
    formatting_style: str = "sentence_case"
    timeout_s: float = 30.0


@dataclass(frozen=True)
class TranscriptionResult:
    """Result of a single transcription request."""

    text: str
    audio_s: float = 0.0
    inference_s: float = 0.0
    tokens_generated: int = 0
    realtime_factor: float = 0.0
    device: str = "cpu"


@dataclass(frozen=True)
class LoadReport:
    """Outcome of loading a model."""

    device: str
    load_seconds: float = 0.0
    vram_estimate_gb: float = 0.0
    max_clip_seconds: float = 0.0


@dataclass(frozen=True)
class HealthReport:
    """Health/readiness snapshot of a service."""

    status: str            # "ok" | "model_missing" | "unreachable" | "not_loaded"
    detail: str = ""
    model_loaded: bool = False
    device: str = ""


@dataclass(frozen=True)
class EngineStats:
    """Cumulative inference statistics; replaces the legacy token_stats tuple."""

    tokens_per_second: float = 0.0
    total_tokens: int = 0
    total_audio_seconds: float = 0.0
    realtime_factor: float = 0.0
    inference_count: int = 0


@runtime_checkable
class TranscriptionService(Protocol):
    """The single interface the UI talks to for all transcription."""

    def descriptor(self) -> EngineDescriptor: ...

    def capabilities(self) -> EngineCapabilities: ...

    def load(self, source: ModelSource, device: str) -> LoadReport: ...

    def unload(self) -> None: ...

    @property
    def is_loaded(self) -> bool: ...

    def transcribe(
        self, audio_16k: np.ndarray, options: TranscriptionOptions
    ) -> TranscriptionResult: ...

    def health(self) -> HealthReport: ...

    def stats(self) -> EngineStats: ...
