"""
Cohere Transcribe 03-2026 engine.

Uses the ``CohereAsrForConditionalGeneration`` model from HuggingFace
transformers for high-accuracy speech recognition (2B parameters).

Supported languages: en, fr, de, it, es, pt, el, nl, pl, zh, ja, ko, vi, ar.
"""

from __future__ import annotations

import logging
import os

import numpy as np

from .base import SpeechEngine

log = logging.getLogger(__name__)

COHERE_REPO_ID = "CohereLabs/cohere-transcribe-03-2026"


class CohereTranscribeEngine(SpeechEngine):
    """Cohere Transcribe 03-2026 — 2B parameter ASR model."""

    def __init__(self) -> None:
        super().__init__()
        self._processor = None
        # Throughput counters for Developer Panel
        self._total_tokens: int = 0
        self._total_audio_sec: float = 0.0
        self._last_tok_per_sec: float = 0.0
        self._last_realtime_factor: float = 0.0
        self._last_inference_time: float = 0.0  # monotonic timestamp
        self._device: str = "cpu"
        self._actual_device: str = "cpu"
        # Monotonically increasing counter — incremented after every chunk
        # transcription so the Developer Panel sparkline can dedupe samples
        # without depending on a decay window.
        self._inference_seq: int = 0

    # ── Abstract interface ───────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "cohere"

    @property
    def vram_estimate_gb(self) -> float:
        return 5.0

    @property
    def actual_device(self) -> str:
        return self._actual_device

    def load(self, model_path: str, device: str = "cuda") -> None:
        import torch
        from transformers import AutoProcessor, CohereAsrForConditionalGeneration

        self._device = device
        cohere_dir = os.path.join(model_path, "cohere")

        # Download if not present locally
        if not os.path.isdir(cohere_dir) or not os.path.isfile(
            os.path.join(cohere_dir, "config.json")
        ):
            log.info("Cohere model not found at %s — downloading…", cohere_dir)
            from speakeasy.model_downloader import download_model, EXIT_SUCCESS, EXIT_AUTH_REQUIRED
            rc = download_model("cohere", model_path)
            if rc == EXIT_AUTH_REQUIRED:
                raise RuntimeError(
                    f"The Cohere Transcribe model requires authentication. "
                    f"Please provide a HuggingFace token with access to {COHERE_REPO_ID}."
                )
            if rc != EXIT_SUCCESS:
                raise RuntimeError(f"Failed to download Cohere model from {COHERE_REPO_ID}.")

        log.info("Loading Cohere Transcribe from %s", cohere_dir)

        self._processor = AutoProcessor.from_pretrained(cohere_dir)
        self._model = CohereAsrForConditionalGeneration.from_pretrained(
            cohere_dir,
            device_map=device if device == "cuda" else "cpu",
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        )
        model_device = getattr(self._model, "device", device)
        model_device_text = str(model_device).lower()
        self._actual_device = "cuda" if model_device_text.startswith("cuda") else "cpu"

        # The Cohere model's _ensure_decode_pool uses mp.get_context("fork")
        # which is unavailable on Windows (only "spawn" is supported).  Patch
        # the method to use the platform default context instead.
        # Guard: the method only exists in the model's custom code; the
        # built-in transformers class may not expose it.
        if hasattr(self._model, '_ensure_decode_pool'):
            _orig_ensure = self._model._ensure_decode_pool

            def _patched_ensure_decode_pool(processor):
                import multiprocessing as _mp
                # Temporarily replace mp.get_context to return platform default
                _real_get_ctx = _mp.get_context
                _mp.get_context = lambda method=None: _real_get_ctx("spawn") if method == "fork" else _real_get_ctx(method)
                try:
                    return _orig_ensure(processor)
                finally:
                    _mp.get_context = _real_get_ctx

            self._model._ensure_decode_pool = _patched_ensure_decode_pool

        log.info("Cohere Transcribe loaded on %s", self._actual_device)

        # Read model-config limits for chunking and token budget.
        cfg = getattr(self._model, "config", None)
        if cfg is not None:
            self._max_clip_seconds = float(
                getattr(cfg, "max_audio_clip_s", self._max_clip_seconds)
            )
            self._overlap_seconds = float(
                getattr(cfg, "overlap_chunk_second", self._overlap_seconds)
            )
            self._decoder_max_seq = int(
                getattr(cfg, "max_seq_len", self._decoder_max_seq)
            )
        log.info(
            "Cohere limits: max_clip=%.0fs, overlap=%.0fs, decoder_max_seq=%d",
            self._max_clip_seconds, self._overlap_seconds, self._decoder_max_seq,
        )

    def _transcribe_impl(self, audio_16k: np.ndarray, language: str,
                          punctuation: bool = True,
                          timeout: float = 30.0,
                          partial_callback=None) -> str:
        from .audio_utils import chunk_audio, stitch_transcripts
        import time as _time

        duration_sec = len(audio_16k) / 16000
        self._total_audio_sec += duration_sec
        _impl_t0 = _time.monotonic()

        # Read model-level limits from config (set during load).
        max_clip_s = self._max_clip_seconds
        overlap_s = self._overlap_seconds

        # Short-circuit: single-clip fast path (no chunking overhead).
        # Partial callback is not invoked in this path — caller gets the
        # final result via the normal return.
        if duration_sec <= max_clip_s:
            max_tokens = self._token_budget(duration_sec)
            log.info(
                "Transcribing %.1fs audio — 1 chunk, max_new_tokens=%d, "
                "timeout=%.0fs",
                duration_sec, max_tokens, timeout,
            )
            result = self._transcribe_chunk(
                audio_16k, language, punctuation, timeout, max_tokens,
            )
            _wall = _time.monotonic() - _impl_t0
            if _wall > 0:
                self._last_realtime_factor = duration_sec / _wall
            return result

        # Long audio: chunk, transcribe each, stitch.
        chunks = chunk_audio(audio_16k, sr=16000,
                             max_seconds=max_clip_s,
                             overlap_seconds=overlap_s)
        max_tokens = self._token_budget(max_clip_s)
        log.info(
            "Transcribing %.1fs audio — %d chunks (%.0fs each, %.1fs overlap), "
            "max_new_tokens=%d, timeout=%.0fs",
            duration_sec, len(chunks), max_clip_s, overlap_s,
            max_tokens, timeout,
        )

        texts = []
        total = len(chunks)
        for i, chunk in enumerate(chunks):
            chunk_dur = len(chunk) / 16000
            chunk_tokens = self._token_budget(chunk_dur)
            log.info("  chunk %d/%d: %.1fs, max_new_tokens=%d",
                     i + 1, total, chunk_dur, chunk_tokens)
            text = self._transcribe_chunk(
                chunk, language, punctuation, timeout, chunk_tokens,
            )
            texts.append(text)

            # Emit running stitched text for per-chunk partials. Swallow any
            # callback errors so a broken UI slot never breaks transcription.
            if partial_callback is not None:
                try:
                    running = stitch_transcripts(texts)
                    partial_callback(running, i + 1, total)
                except Exception:
                    log.exception("partial_callback raised; ignoring")

        result = stitch_transcripts(texts)
        log.info("Stitched %d chunks → %d chars", len(texts), len(result))
        _wall = _time.monotonic() - _impl_t0
        if _wall > 0:
            self._last_realtime_factor = duration_sec / _wall
        return result

    # ── Helpers ──────────────────────────────────────────────────────────

    # Model config values — set during load(), safe defaults for tests.
    _max_clip_seconds: float = 30.0
    _overlap_seconds: float = 5.0
    _decoder_max_seq: int = 1024

    def _token_budget(self, clip_duration_sec: float) -> int:
        """Compute per-chunk max_new_tokens, clamped to decoder ceiling.

        Heuristic: ~20 tokens per second of speech.  Floored at 128 so
        very short clips still have room; capped at decoder max_seq_len.
        """
        budget = max(128, int(clip_duration_sec * 20))
        return min(budget, self._decoder_max_seq)

    @property
    def token_stats(self) -> tuple[float, int, float, float, int]:
        """Return ``(tok_per_sec, total_tokens, total_audio_sec, realtime_factor, inference_seq)``.

        ``tok_per_sec`` and ``realtime_factor`` are the raw values from the
        last completed chunk transcription (no decay).  ``inference_seq``
        increments by one per completed chunk so consumers (e.g. the
        Developer Panel sparkline) can dedupe samples between polls.
        """
        return (
            self._last_tok_per_sec,
            self._total_tokens,
            self._total_audio_sec,
            self._last_realtime_factor,
            self._inference_seq,
        )

    def _transcribe_chunk(self, audio_16k: np.ndarray, language: str,
                           punctuation: bool, timeout: float,
                           max_new_tokens: int) -> str:
        import torch
        from transformers.generation.stopping_criteria import (
            MaxTimeCriteria,
            StoppingCriteriaList,
        )

        inputs = self._processor(
            audio_16k,
            sampling_rate=16000,
            return_tensors="pt",
            language=language or "en",
            punctuation=punctuation,
        )
        # Keep floating inputs aligned with the loaded model dtype so CUDA
        # convolution layers do not see float32 features against float16 weights.
        model_dtype = getattr(self._model, "dtype", None)
        if model_dtype is None:
            try:
                model_dtype = next(self._model.parameters()).dtype
            except (AttributeError, StopIteration):
                model_dtype = None

        converted_inputs = {}
        for key, value in inputs.items():
            if not hasattr(value, "to"):
                converted_inputs[key] = value
                continue

            tensor = value.to(self._model.device)
            if model_dtype is not None and torch.is_floating_point(tensor):
                tensor = tensor.to(dtype=model_dtype)
            converted_inputs[key] = tensor
        inputs = converted_inputs

        stopping = StoppingCriteriaList([MaxTimeCriteria(max_time=timeout)])

        import time as _time
        _t0 = _time.monotonic()

        with torch.no_grad():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                stopping_criteria=stopping,
            )

        # Track throughput for Developer Panel
        import time as _time
        _elapsed = _time.monotonic() - _t0
        gen_tokens = output_ids.shape[-1]
        self._total_tokens += gen_tokens
        if _elapsed > 0:
            self._last_tok_per_sec = gen_tokens / _elapsed
        self._last_inference_time = _time.monotonic()
        self._inference_seq += 1

        text = self._processor.decode(output_ids, skip_special_tokens=True)
        if isinstance(text, (list, tuple)):
            text = text[0] if text else ""
        return str(text).strip()

    def unload(self) -> None:
        self._processor = None
        self._release_model()
