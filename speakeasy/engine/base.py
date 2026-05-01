"""
Engine abstraction — ABC defining the contract all speech engines must follow.
"""

from __future__ import annotations

import gc
import logging
from abc import ABC, abstractmethod
from typing import Callable, Optional

import numpy as np

from .audio_utils import ensure_16khz

# Partial-result callback: (stitched_text_so_far, chunk_index_1based, total_chunks).
# Raised exceptions are logged and swallowed by the engine; callbacks must not
# break the transcription loop.
PartialCallback = Callable[[str, int, int], None]

log = logging.getLogger(__name__)


class SpeechEngine(ABC):
    """Base class for all speech-to-text engines.

    Provides shared ``is_loaded``, ``_release_model()``, and a
    ``transcribe()`` wrapper that resamples to 16 kHz and guards
    against empty audio / unloaded model.  Subclasses implement
    ``_transcribe_impl()`` for the engine-specific inference path.
    """

    def __init__(self) -> None:
        self._model = None

    # ── Abstract interface ───────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable engine name."""

    @property
    @abstractmethod
    def vram_estimate_gb(self) -> float:
        """Estimated VRAM usage in GB when loaded."""

    @abstractmethod
    def load(self, model_path: str, device: str = "cuda") -> None:
        """Load model weights into memory/VRAM."""

    @abstractmethod
    def _transcribe_impl(self, audio_16k: np.ndarray, language: str,
                          punctuation: bool = True,
                          timeout: float = 30.0,
                          partial_callback: Optional[PartialCallback] = None) -> str:
        """Engine-specific transcription of 16 kHz mono float32 audio.

        If ``partial_callback`` is provided and the engine transcribes the
        audio in multiple chunks, the callback is invoked after each chunk
        with the running stitched text. Callback errors must be logged and
        swallowed — they must never break the transcription loop.
        """

    @abstractmethod
    def unload(self) -> None:
        """Release model and free GPU memory."""

    # ── Concrete shared logic ────────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        """Whether the model is currently loaded and ready for inference."""
        return self._model is not None

    def transcribe(self, audio: np.ndarray, sample_rate: int,
                    language: str = "en", punctuation: bool = True,
                    timeout: float = 30.0,
                    partial_callback: Optional[PartialCallback] = None) -> str:
        """Resample to 16 kHz, guard empty/unloaded, then delegate."""
        if self._model is None:
            raise RuntimeError(f"{self.name} model not loaded")
        audio_16k = ensure_16khz(audio, sample_rate)
        if len(audio_16k) == 0:
            return ""
        return self._transcribe_impl(audio_16k, language, punctuation=punctuation,
                                      timeout=timeout,
                                      partial_callback=partial_callback)

    def _release_model(self) -> None:
        """Delete model reference and free GPU memory."""
        if self._model is not None:
            del self._model
            self._model = None
        _cleanup_gpu_memory()
        log.info("%s model unloaded", self.name)


def _cleanup_gpu_memory() -> None:
    """Best-effort GPU memory cleanup."""
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
