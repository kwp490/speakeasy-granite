"""Deterministic synthetic audio fixtures for the benchmark harness (Phase 0).

Generates ``10s.wav``, ``30s.wav`` and ``120s.wav`` as 16 kHz mono PCM16 WAV
files in this directory.  The content is a seeded mixture of frequency-swept
tones plus low-amplitude noise — it is *not* speech, so it carries no
reference transcript (WER is skipped for these fixtures).  Their purpose is to
exercise the record → resample → chunk → inference latency path at known
durations on every machine, reproducibly and without shipping copyrighted
audio.

Run::

    python tests/fixtures/audio/generate_fixtures.py
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

TARGET_SR = 16000
DURATIONS_S = (10, 30, 120)
SEED = 1729


def _synthesize(duration_s: int, sr: int = TARGET_SR) -> np.ndarray:
    rng = np.random.default_rng(SEED + duration_s)
    t = np.linspace(0.0, duration_s, duration_s * sr, endpoint=False)

    # A slow sine sweep (200 Hz → 3 kHz) keeps the resampler honest, while a
    # second steady tone and a touch of noise give the chunker varied content.
    sweep = 0.35 * np.sin(2 * np.pi * (200 + (2800 / duration_s) * t) * t)
    tone = 0.20 * np.sin(2 * np.pi * 440 * t)
    noise = 0.02 * rng.standard_normal(t.shape)
    signal = sweep + tone + noise

    peak = float(np.max(np.abs(signal))) or 1.0
    signal = (signal / peak) * 0.9
    return (signal * 32767.0).astype("<i2")


def _write_wav(path: Path, samples: np.ndarray, sr: int = TARGET_SR) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(samples.tobytes())


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)
    for duration in DURATIONS_S:
        path = out_dir / f"{duration}s.wav"
        _write_wav(path, _synthesize(duration))
        print(f"wrote {path} ({duration}s)")


if __name__ == "__main__":
    main()
