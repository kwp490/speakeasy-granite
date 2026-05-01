"""
Audio utilities for engine preprocessing — resampling and chunking.
"""

from __future__ import annotations

import re
from typing import List

import numpy as np

TARGET_SR = 16000


def ensure_16khz(audio: np.ndarray, source_sr: int) -> np.ndarray:
    """Resample audio to 16 kHz if needed.  Input must be 1D float32."""
    if source_sr == TARGET_SR:
        return audio
    if len(audio) == 0:
        return np.array([], dtype=np.float32)
    import librosa

    return librosa.resample(audio, orig_sr=source_sr, target_sr=TARGET_SR).astype(
        np.float32
    )


def chunk_audio(
    audio: np.ndarray,
    sr: int,
    max_seconds: float,
    overlap_seconds: float,
) -> List[np.ndarray]:
    """Split audio into overlapping chunks.

    Returns a list of 1D float32 arrays, each at most *max_seconds* long.
    Adjacent chunks overlap by *overlap_seconds*.  Both parameters are
    required — callers must pass values that match their model's limits.
    """
    max_samples = int(max_seconds * sr)
    overlap_samples = int(overlap_seconds * sr)
    step = max_samples - overlap_samples
    if step <= 0:
        raise ValueError(
            f"overlap_seconds ({overlap_seconds}) must be less than "
            f"max_seconds ({max_seconds})"
        )

    if len(audio) <= max_samples:
        return [audio]

    chunks: List[np.ndarray] = []
    start = 0
    while start < len(audio):
        end = min(start + max_samples, len(audio))
        chunks.append(audio[start:end])
        if end >= len(audio):
            break
        start += step
    return chunks


# ── Transcript stitching ─────────────────────────────────────────────────

# Punctuation that the model may attach to the last word in a chunk.
_TRAILING_PUNCT = re.compile(r"[.,;:!?\-—…]+$")


def _normalize_word(word: str) -> str:
    """Lower-case and strip trailing punctuation for overlap comparison."""
    return _TRAILING_PUNCT.sub("", word).lower()


def stitch_transcripts(texts: List[str], max_overlap_words: int = 25) -> str:
    """Join chunk transcripts, deduplicating overlap at boundaries.

    Compares the suffix of the previous result against the prefix of the
    next chunk using case- and punctuation-insensitive matching, then
    keeps the *next* chunk's version of the overlapping region (which has
    more right-side context and therefore better punctuation/casing).

    *max_overlap_words* limits how many trailing/leading words to compare;
    callers may raise it when using wider audio overlaps.
    """
    if not texts:
        return ""
    result = texts[0]
    for nxt in texts[1:]:
        if not nxt:
            continue
        if not result:
            result = nxt
            continue

        words_r = result.split()
        words_n = nxt.split()

        # Build normalised versions once for the comparison window.
        check_len = min(len(words_r), len(words_n), max_overlap_words)
        norm_r = [_normalize_word(w) for w in words_r[-check_len:]]
        norm_n = [_normalize_word(w) for w in words_n[:check_len]]

        # Find the longest suffix of norm_r that equals a prefix of norm_n.
        best_overlap = 0
        for k in range(1, check_len + 1):
            if norm_r[-k:] == norm_n[:k]:
                best_overlap = k

        if best_overlap > 0:
            # Drop the overlapping words from result, keep next chunk's
            # version (it has better right-side context for punctuation).
            kept = words_r[: len(words_r) - best_overlap]
            result = " ".join(kept) + " " + nxt if kept else nxt
        else:
            result = result + " " + nxt
    return result.strip()
