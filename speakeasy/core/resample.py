"""Client-side resampling to 16 kHz mono float32.

Moved out of the engine layer so resampling happens *before* audio crosses any
process/network boundary, fixing the wire-format ambiguity: a transcription
service always receives 16 kHz mono float32.

The heavy resampling library is imported lazily inside :func:`ensure_16khz` so
this module imports cleanly in a torch-free, librosa-free interpreter.  ``soxr``
is the single supported resampler (small, fast, no numba/llvmlite/scipy chain).
``librosa`` is no longer a declared dependency (Phase 2.5); the ``except
ImportError`` branch below is retained purely as defensive graceful-degradation
for an environment that happens to ship librosa but not soxr.  In practice soxr
is always present, so the fallback never triggers.
"""

from __future__ import annotations

import numpy as np

TARGET_SR = 16000


def ensure_16khz(audio: np.ndarray, source_sr: int) -> np.ndarray:
    """Resample 1D float32 *audio* to 16 kHz if needed."""
    if source_sr == TARGET_SR:
        return audio
    if len(audio) == 0:
        return np.array([], dtype=np.float32)
    return _resample(audio, source_sr, TARGET_SR)


def _resample(audio: np.ndarray, source_sr: int, target_sr: int) -> np.ndarray:
    try:
        import soxr

        return soxr.resample(audio, source_sr, target_sr).astype(np.float32)
    except ImportError:
        import librosa

        return librosa.resample(
            audio, orig_sr=source_sr, target_sr=target_sr
        ).astype(np.float32)
