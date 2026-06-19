"""soxr-vs-librosa resampling equivalence (Phase 2.5 safety net).

Phase 2.5 swaps the 16 kHz resampling kernel from ``librosa.resample`` to
``soxr.resample``.  This is a *behaviour-equivalence* change: transcription
output must be indistinguishable from the librosa baseline within tolerance.

These tests resample the SAME input with both libraries from representative
source rates (44100 and 48000 -> 16000) and assert the outputs agree within a
documented tolerance.  They do NOT assert exact equality: soxr and librosa use
different anti-aliasing kernels, so a small numerical delta is expected and
acceptable.  The thresholds below were measured on these signals; see the
Phase 2.5 entry in ``docs/REARCHITECTURE-PROGRESS.md`` for the rationale.

If a future change makes soxr and librosa diverge beyond these thresholds, this
test fails *before* the swap ships — that is the point of the safety net.
"""

import numpy as np
import pytest

librosa = pytest.importorskip("librosa")
soxr = pytest.importorskip("soxr")

from speakeasy.core.resample import ensure_16khz

TARGET_SR = 16000

# Tolerances measured on the band-limited test signals below (interior region,
# excluding the first/last few ms of filter-transient edge where the two
# kernels legitimately differ most).  Peak signal amplitude is ~1.0, so these
# are absolute thresholds on a unit-scale waveform.
MAX_ABS_TOL = 2.5e-2  # peak absolute deviation, unit-amplitude signal
RMS_TOL = 3.0e-3      # root-mean-square deviation across the interior


def _multitone(duration_s: float, sr: int, seed: int = 0) -> np.ndarray:
    """Band-limited multi-tone + light noise test signal (mono float32).

    All tones sit comfortably below the 16 kHz Nyquist (8 kHz) so the result is
    dominated by genuine resampling behaviour rather than aliasing differences
    in content the target rate cannot represent.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(int(duration_s * sr), dtype=np.float64) / sr
    freqs = (110.0, 440.0, 1000.0, 2500.0, 5000.0, 7000.0)
    sig = np.zeros_like(t)
    for f in freqs:
        sig += np.sin(2.0 * np.pi * f * t + rng.uniform(0, 2 * np.pi))
    sig += 0.05 * rng.standard_normal(t.shape)
    sig /= np.max(np.abs(sig))
    return sig.astype(np.float32)


def _interior(a: np.ndarray, b: np.ndarray, edge_ms: float = 5.0):
    """Trim equal-length leading/trailing edge samples from both arrays.

    Filter transients at the very start/end differ most between kernels; the
    perceptually relevant comparison is the steady-state interior.
    """
    n = min(len(a), len(b))
    edge = int(edge_ms * 1e-3 * TARGET_SR)
    edge = min(edge, n // 4)
    return a[edge:n - edge], b[edge:n - edge]


@pytest.mark.parametrize("source_sr", [44100, 48000])
def test_soxr_matches_librosa_on_multitone(source_sr):
    audio = _multitone(2.0, source_sr)

    out_soxr = soxr.resample(audio, source_sr, TARGET_SR).astype(np.float32)
    out_librosa = librosa.resample(
        audio, orig_sr=source_sr, target_sr=TARGET_SR
    ).astype(np.float32)

    # Length agreement: both kernels target the same rate; allow a 1-sample
    # rounding difference at the tail.
    assert abs(len(out_soxr) - len(out_librosa)) <= 1

    a, b = _interior(out_soxr, out_librosa)
    max_abs = float(np.max(np.abs(a - b)))
    rms = float(np.sqrt(np.mean((a - b) ** 2)))

    assert max_abs <= MAX_ABS_TOL, (
        f"{source_sr}->{TARGET_SR}: max abs error {max_abs:.4e} > {MAX_ABS_TOL:.1e}"
    )
    assert rms <= RMS_TOL, (
        f"{source_sr}->{TARGET_SR}: RMS error {rms:.4e} > {RMS_TOL:.1e}"
    )


@pytest.mark.parametrize("source_sr", [44100, 48000])
def test_ensure_16khz_matches_librosa(source_sr):
    """The production ``ensure_16khz`` (soxr primary) must track librosa too."""
    audio = _multitone(2.0, source_sr, seed=1)

    out_app = ensure_16khz(audio, source_sr)
    out_librosa = librosa.resample(
        audio, orig_sr=source_sr, target_sr=TARGET_SR
    ).astype(np.float32)

    assert out_app.dtype == np.float32
    assert abs(len(out_app) - len(out_librosa)) <= 1

    a, b = _interior(out_app, out_librosa)
    max_abs = float(np.max(np.abs(a - b)))
    rms = float(np.sqrt(np.mean((a - b) ** 2)))

    assert max_abs <= MAX_ABS_TOL, f"max abs error {max_abs:.4e}"
    assert rms <= RMS_TOL, f"RMS error {rms:.4e}"


def test_ensure_16khz_passthrough_at_target_rate():
    audio = _multitone(0.5, TARGET_SR)
    out = ensure_16khz(audio, TARGET_SR)
    # Already 16 kHz -> identical object, no resampling.
    assert out is audio
