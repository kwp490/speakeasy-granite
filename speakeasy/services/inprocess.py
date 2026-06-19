"""In-process transcription service.

Adapts a duck-typed speech engine (the existing Granite engine, or the
:class:`~speakeasy.engines.fake.FakeEngine` test double) to the
:class:`~speakeasy.core.contract.TranscriptionService` protocol.

This adapter is intentionally torch-free: it imports no ML packages and never
inspects engine internals beyond the documented duck-typed surface
(``name``, ``load``, ``transcribe``, ``unload``, ``is_loaded``, and the
optional ``capabilities``/``configure_prompt_options``/``token_stats``/
``actual_device``/``vram_estimate_gb`` members).
"""

from __future__ import annotations

import time

import numpy as np

from .. import __version__
from ..core.contract import (
    EngineCapabilities,
    EngineDescriptor,
    EngineStats,
    HealthReport,
    LoadReport,
    TranscriptionOptions,
    TranscriptionResult,
)
from ..core.errors import EngineError, ModelNotConfigured
from ..core.model_source import (
    LocalDirSource,
    ManagedSource,
    ModelSource,
    RemoteSource,
)

_TARGET_SR = 16000


class InProcessEngineService:
    """Wrap a speech engine and expose the transcription contract."""

    def __init__(self, engine, *, app_version: str = __version__) -> None:
        self._engine = engine
        self._app_version = app_version
        self._device = "cpu"

    # ── Identity / capabilities ──────────────────────────────────────────

    def descriptor(self) -> EngineDescriptor:
        return EngineDescriptor(
            name=getattr(self._engine, "name", "unknown"),
            version=self._app_version,
            is_remote=False,
        )

    def capabilities(self) -> EngineCapabilities:
        provider = getattr(self._engine, "capabilities", None)
        if callable(provider):
            return provider()
        return self._generic_capabilities()

    # ── Lifecycle ────────────────────────────────────────────────────────

    def load(self, source: ModelSource, device: str) -> LoadReport:
        path = self._source_to_path(source)
        self._device = device
        start = time.monotonic()
        self._engine.load(path, device)
        load_seconds = time.monotonic() - start
        return LoadReport(
            device=str(getattr(self._engine, "actual_device", device)),
            load_seconds=load_seconds,
            vram_estimate_gb=float(getattr(self._engine, "vram_estimate_gb", 0.0) or 0.0),
            max_clip_seconds=float(getattr(self._engine, "_max_clip_seconds", 0.0) or 0.0),
        )

    def unload(self) -> None:
        self._engine.unload()

    @property
    def is_loaded(self) -> bool:
        return bool(getattr(self._engine, "is_loaded", False))

    # ── Inference ────────────────────────────────────────────────────────

    def transcribe(
        self, audio_16k: np.ndarray, options: TranscriptionOptions
    ) -> TranscriptionResult:
        configure = getattr(self._engine, "configure_prompt_options", None)
        if callable(configure):
            configure(
                speech_task=options.task,
                translation_target_language=options.translation_target,
                keyword_bias=options.keyword_bias,
                formatting_style=options.formatting_style,
            )

        tokens_before = self._read_stats().total_tokens
        start = time.monotonic()
        text = self._engine.transcribe(
            audio_16k,
            sample_rate=_TARGET_SR,
            language=options.language,
            punctuation=options.punctuation,
            timeout=options.timeout_s,
        )
        inference_s = time.monotonic() - start

        stats = self._read_stats()
        audio_s = len(audio_16k) / float(_TARGET_SR)
        return TranscriptionResult(
            text=text,
            audio_s=audio_s,
            inference_s=inference_s,
            tokens_generated=max(0, stats.total_tokens - tokens_before),
            realtime_factor=stats.realtime_factor,
            device=str(getattr(self._engine, "actual_device", self._device)),
        )

    # ── Status ───────────────────────────────────────────────────────────

    def health(self) -> HealthReport:
        loaded = self.is_loaded
        return HealthReport(
            status="ok" if loaded else "not_loaded",
            model_loaded=loaded,
            device=str(getattr(self._engine, "actual_device", self._device)),
        )

    def probe_device(self) -> HealthReport:
        """Actively verify the loaded device is still usable.

        For CUDA this performs a tiny allocation to detect a context that was
        silently corrupted by sleep/resume; the heavy ``torch`` import happens
        here (lazily) so the UI never imports it at module scope.  Non-CUDA
        devices delegate to :meth:`health`.
        """
        device = str(getattr(self._engine, "actual_device", self._device))
        if not device.lower().startswith("cuda"):
            return self.health()
        try:
            import torch

            probe = torch.zeros(1, device="cuda")
            del probe
        except Exception as exc:  # noqa: BLE001 - any failure means the device is gone
            return HealthReport(
                status="device_lost",
                detail=str(exc),
                model_loaded=self.is_loaded,
                device=device,
            )
        return HealthReport(status="ok", model_loaded=self.is_loaded, device=device)

    def stats(self) -> EngineStats:
        return self._read_stats()

    # ── Internals ────────────────────────────────────────────────────────

    def _read_stats(self) -> EngineStats:
        token_stats = getattr(self._engine, "token_stats", None)
        if not token_stats:
            return EngineStats()
        tps, total_tokens, total_audio, rtf, seq = token_stats
        return EngineStats(
            tokens_per_second=float(tps),
            total_tokens=int(total_tokens),
            total_audio_seconds=float(total_audio),
            realtime_factor=float(rtf),
            inference_count=int(seq),
        )

    def _generic_capabilities(self) -> EngineCapabilities:
        devices = ("cuda", "cpu") if self._device == "cuda" else ("cpu",)
        return EngineCapabilities(
            languages=("auto", "en"),
            supports_translation=hasattr(self._engine, "configure_prompt_options"),
            translation_targets=("English",),
            supports_keyword_bias=hasattr(self._engine, "configure_prompt_options"),
            supports_timestamps=False,
            supports_streaming=False,
            formatting_styles=("sentence_case",),
            devices=devices,
            max_clip_seconds=float(getattr(self._engine, "_max_clip_seconds", 30.0) or 30.0),
            is_remote=False,
        )

    @staticmethod
    def _source_to_path(source: ModelSource) -> str:
        if isinstance(source, RemoteSource):
            raise EngineError(
                "In-process service cannot load a remote model source; "
                "use a remote client instead."
            )
        if isinstance(source, (ManagedSource, LocalDirSource)):
            if not source.path:
                raise ModelNotConfigured("Model source path is empty.")
            return source.path
        raise TypeError(f"Unsupported model source: {type(source).__name__}")
