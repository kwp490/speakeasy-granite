"""Deterministic in-package speech-engine double.

``FakeEngine`` mimics the duck-typed surface the in-process service adapter
relies on (``name``, ``load``, ``transcribe``, ``unload``, ``is_loaded``,
``token_stats``, ``actual_device``, ``configure_prompt_options``) without any
ML dependency.  It is the test double every higher-level suite builds on and
also backs a future ``--selftest`` mode.

It deliberately does NOT inherit from ``speakeasy.engine.base.SpeechEngine`` so
importing it never triggers the engine registry's torch import.  The adapter
treats engines structurally, so a faithful duck implementation is sufficient.
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np

from ..core.contract import EngineCapabilities

_TARGET_SR = 16000


class FakeEngine:
    """A deterministic, dependency-free speech engine for tests and selftest."""

    def __init__(
        self,
        *,
        transcript: Optional[str] = None,
        latency_s: float = 0.0,
        tokens_per_call: int = 4,
        fail_on_load: Optional[BaseException] = None,
        fail_on_transcribe: Optional[BaseException] = None,
        devices: tuple[str, ...] = ("cpu",),
        vram_estimate: float = 0.0,
        max_clip_seconds: float = 30.0,
    ) -> None:
        self._transcript = transcript
        self._latency_s = max(0.0, latency_s)
        self._tokens_per_call = max(0, tokens_per_call)
        self._fail_on_load = fail_on_load
        self._fail_on_transcribe = fail_on_transcribe
        self._devices = devices
        self._vram_estimate = vram_estimate
        self._max_clip_seconds = max_clip_seconds

        self._model = None
        self._device = "cpu"
        self._actual_device = "cpu"

        # Cumulative stats mirroring the Granite engine's token_stats tuple.
        self._total_tokens = 0
        self._total_audio_sec = 0.0
        self._last_tok_per_sec = 0.0
        self._last_realtime_factor = 0.0
        self._inference_seq = 0

        # Prompt options captured via configure_prompt_options().
        self._speech_task = "transcribe"
        self._translation_target_language = "English"
        self._keyword_bias = ""
        self._formatting_style = "sentence_case"

    # ── Identity / capability surface ────────────────────────────────────

    @property
    def name(self) -> str:
        return "fake"

    @property
    def vram_estimate_gb(self) -> float:
        return self._vram_estimate

    @property
    def actual_device(self) -> str:
        return self._actual_device

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            languages=("auto", "en"),
            supports_translation=True,
            translation_targets=("English",),
            supports_keyword_bias=True,
            supports_timestamps=False,
            supports_streaming=False,
            formatting_styles=("sentence_case", "plain_text"),
            devices=self._devices,
            max_clip_seconds=self._max_clip_seconds,
            is_remote=False,
        )

    @property
    def token_stats(self) -> tuple[float, int, float, float, int]:
        return (
            self._last_tok_per_sec,
            self._total_tokens,
            self._total_audio_sec,
            self._last_realtime_factor,
            self._inference_seq,
        )

    # ── Prompt-options side channel (kept for adapter compatibility) ─────

    def configure_prompt_options(
        self,
        *,
        speech_task: str = "transcribe",
        translation_target_language: str = "English",
        keyword_bias: str = "",
        formatting_style: str = "sentence_case",
    ) -> None:
        self._speech_task = speech_task
        self._translation_target_language = translation_target_language
        self._keyword_bias = keyword_bias
        self._formatting_style = formatting_style

    # ── Lifecycle ────────────────────────────────────────────────────────

    def load(self, model_path: str, device: str = "cpu") -> None:
        if self._fail_on_load is not None:
            raise self._fail_on_load
        self._device = device
        self._actual_device = "cuda" if device == "cuda" and "cuda" in self._devices else "cpu"
        self._model = object()

    def unload(self) -> None:
        self._model = None

    # ── Inference ────────────────────────────────────────────────────────

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = _TARGET_SR,
        language: str = "en",
        punctuation: bool = True,
        timeout: float = 30.0,
    ) -> str:
        if self._model is None:
            raise RuntimeError("fake model not loaded")
        if self._fail_on_transcribe is not None:
            raise self._fail_on_transcribe
        if len(audio) == 0:
            return ""

        duration_sec = len(audio) / float(sample_rate or _TARGET_SR)
        self._total_audio_sec += duration_sec

        start = time.perf_counter()
        if self._latency_s:
            time.sleep(self._latency_s)
        wall = time.perf_counter() - start

        self._total_tokens += self._tokens_per_call
        self._inference_seq += 1
        if wall > 0:
            self._last_tok_per_sec = self._tokens_per_call / wall
            self._last_realtime_factor = duration_sec / wall
        else:
            self._last_tok_per_sec = 0.0
            self._last_realtime_factor = 0.0

        return self._render(len(audio), language)

    def _render(self, n_samples: int, language: str) -> str:
        if self._transcript is not None:
            return self._transcript
        verb = "translate" if self._speech_task == "translate" else "transcribe"
        return f"fake {verb} lang={language} samples={n_samples}"
