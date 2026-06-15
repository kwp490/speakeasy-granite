"""SpeakEasy AI — benchmark harness (Phase 0 baseline tooling).

Measures the numbers every later re-architecture phase is judged against:
cold-start, model-load time, per-fixture transcription latency (p50/p95),
realtime factor (RTF), peak RAM / VRAM, and word error rate (WER) against
committed reference transcripts.

The harness is intentionally dependency-light at import time so that
``--smoke`` runs in CI without torch, transformers, or a downloaded model.
Heavy imports (the real Granite engine) happen only on the full path.

Usage
-----
Smoke run (CI; no torch / no model required)::

    python tools/bench.py --smoke --device cpu --output bench-smoke.json

Full baseline run on benchmark hardware::

    python tools/bench.py --device cuda --output docs/benchmarks/run-gpu.json
    python tools/bench.py --device cpu  --output docs/benchmarks/run-cpu.json

Fixtures live in ``tests/fixtures/audio/{10s,30s,120s}.wav`` plus the bundled
``speakeasy/assets/validation.wav``.  Reference transcripts (for WER) live in
``tests/fixtures/audio/references.json``.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "audio"
_VALIDATION_WAV = _REPO_ROOT / "speakeasy" / "assets" / "validation.wav"
_REFERENCES = _FIXTURE_DIR / "references.json"

TARGET_SR = 16000


# ──────────────────────────────────────────────────────────────────────────
#  Result dataclasses (define the committed JSON schema)
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class FixtureResult:
    name: str
    duration_s: float
    iterations: int
    latencies_s: list[float]
    p50_latency_s: float
    p95_latency_s: float
    rtf: float
    reference: Optional[str]
    hypothesis: Optional[str]
    wer: Optional[float]


@dataclass
class BenchResult:
    schema_version: int = 1
    app_version: str = ""
    timestamp: str = ""
    smoke: bool = False
    device: str = "cpu"
    host: dict = field(default_factory=dict)
    engine: dict = field(default_factory=dict)
    cold_start_ms: Optional[float] = None
    model_load_s: Optional[float] = None
    peak_ram_mb: Optional[float] = None
    peak_vram_mb: Optional[float] = None
    fixtures: list[FixtureResult] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
#  Audio + metric helpers
# ──────────────────────────────────────────────────────────────────────────


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Read a WAV file as mono float32 in [-1, 1] using only the stdlib."""
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())

    if sampwidth == 2:
        data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    elif sampwidth == 1:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported sample width {sampwidth} in {path}")

    if n_channels > 1:
        data = data.reshape(-1, n_channels)[:, 0]
    return data, sr


def _wer(reference: str, hypothesis: str) -> float:
    """Word error rate via Levenshtein distance on whitespace tokens."""
    ref = reference.lower().split()
    hyp = hypothesis.lower().split()
    if not ref:
        return 0.0 if not hyp else 1.0

    # Classic DP edit distance over word sequences.
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, start=1):
            cost = 0 if r == h else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[len(hyp)] / len(ref)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def _peak_ram_mb() -> Optional[float]:
    """Peak working-set size of the current process in MB (Windows/psapi)."""
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _PMC()
        counters.cb = ctypes.sizeof(_PMC)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ):
            return counters.PeakWorkingSetSize / (1024 * 1024)
    except Exception:
        pass
    return None


def _peak_vram_mb(device: str) -> Optional[float]:
    if device != "cuda":
        return None
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.max_memory_allocated() / (1024 * 1024)
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────────────────────────────────
#  Engines
# ──────────────────────────────────────────────────────────────────────────


class _SmokeEngine:
    """Zero-dependency stand-in used by ``--smoke``.

    Returns a deterministic transcript and a tiny, audio-length-proportional
    sleep so the harness exercises its full timing/reporting path without
    torch, transformers, or a downloaded model.  Replaced by FakeEngine in
    Phase 1 once the formal contract lands.
    """

    name = "smoke"
    actual_device = "cpu"

    def load(self, model_path: str, device: str = "cpu") -> None:  # noqa: ARG002
        time.sleep(0.01)

    def transcribe(self, audio: np.ndarray, sample_rate: int, **_: object) -> str:
        duration = len(audio) / float(sample_rate or TARGET_SR)
        time.sleep(min(0.05, duration * 0.001))
        return "testing one two three"

    def unload(self) -> None:
        pass


def _build_real_engine(device: str, model_path: str):
    """Import and construct the real Granite engine (heavy imports here only)."""
    from speakeasy.engine.granite_transcribe import GraniteTranscribeEngine

    engine = GraniteTranscribeEngine()
    engine.load(model_path, device=device)
    return engine


# ──────────────────────────────────────────────────────────────────────────
#  Fixture discovery
# ──────────────────────────────────────────────────────────────────────────


def _load_references() -> dict[str, Optional[str]]:
    if _REFERENCES.is_file():
        try:
            return json.loads(_REFERENCES.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _discover_fixtures(extra_dir: Optional[Path]) -> list[Path]:
    paths: list[Path] = []
    search_dir = extra_dir or _FIXTURE_DIR
    for name in ("10s.wav", "30s.wav", "120s.wav"):
        candidate = search_dir / name
        if candidate.is_file():
            paths.append(candidate)
    if _VALIDATION_WAV.is_file():
        paths.append(_VALIDATION_WAV)
    return paths


# ──────────────────────────────────────────────────────────────────────────
#  Core run
# ──────────────────────────────────────────────────────────────────────────


def run_benchmark(
    *,
    device: str,
    smoke: bool,
    model_path: str,
    iterations: int,
    warmup: int,
    fixtures_dir: Optional[Path],
) -> BenchResult:
    references = _load_references()
    fixtures = _discover_fixtures(fixtures_dir)
    if not fixtures:
        raise SystemExit(
            f"No benchmark fixtures found under {fixtures_dir or _FIXTURE_DIR}. "
            "Run tests/fixtures/audio/generate_fixtures.py first."
        )

    try:
        from speakeasy import __version__ as app_version
    except Exception:
        app_version = "unknown"

    result = BenchResult(
        app_version=app_version,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        smoke=smoke,
        device=device,
        host={
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
    )

    # Cold start: time to construct + load the engine.
    cold_start = time.perf_counter()
    if smoke:
        engine = _SmokeEngine()
        load_start = time.perf_counter()
        engine.load(model_path, device=device)
        result.model_load_s = time.perf_counter() - load_start
    else:
        load_start = time.perf_counter()
        engine = _build_real_engine(device, model_path)
        result.model_load_s = time.perf_counter() - load_start
        try:
            import torch

            result.host["torch"] = torch.__version__
            result.host["cuda_available"] = bool(torch.cuda.is_available())
        except Exception:
            pass
    result.cold_start_ms = (time.perf_counter() - cold_start) * 1000.0
    result.engine = {
        "name": getattr(engine, "name", "unknown"),
        "actual_device": getattr(engine, "actual_device", device),
        "model_path": model_path,
    }

    for path in fixtures:
        audio, sr = _read_wav(path)
        duration_s = len(audio) / float(sr or TARGET_SR)

        for _ in range(max(0, warmup)):
            engine.transcribe(audio, sr)

        latencies: list[float] = []
        hypothesis = ""
        for _ in range(max(1, iterations)):
            t0 = time.perf_counter()
            hypothesis = engine.transcribe(audio, sr)
            latencies.append(time.perf_counter() - t0)

        ref = references.get(path.name)
        wer_val = _wer(ref, hypothesis) if ref else None
        p50 = _percentile(latencies, 50)
        result.fixtures.append(
            FixtureResult(
                name=path.name,
                duration_s=round(duration_s, 3),
                iterations=len(latencies),
                latencies_s=[round(x, 4) for x in latencies],
                p50_latency_s=round(p50, 4),
                p95_latency_s=round(_percentile(latencies, 95), 4),
                rtf=round(duration_s / p50, 3) if p50 > 0 else 0.0,
                reference=ref,
                hypothesis=hypothesis,
                wer=round(wer_val, 4) if wer_val is not None else None,
            )
        )

    result.peak_ram_mb = round(v, 1) if (v := _peak_ram_mb()) is not None else None
    vram = _peak_vram_mb(device)
    result.peak_vram_mb = round(vram, 1) if vram is not None else None

    try:
        engine.unload()
    except Exception:
        pass
    return result


def _to_serializable(result: BenchResult) -> dict:
    data = asdict(result)
    data["fixtures"] = [asdict(f) if not isinstance(f, dict) else f for f in result.fixtures]
    return data


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="SpeakEasy benchmark harness")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cpu")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Use the zero-dependency smoke engine (no torch / no model).",
    )
    parser.add_argument(
        "--model-path",
        default="",
        help="Model root containing 'granite/' (full runs only).",
    )
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help="Override the directory holding 10s/30s/120s WAV fixtures.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the JSON report to this path (also printed to stdout).",
    )
    args = parser.parse_args(argv)

    if args.smoke:
        iterations, warmup = max(1, min(args.iterations, 2)), 0
    else:
        iterations, warmup = args.iterations, args.warmup

    model_path = args.model_path
    if not args.smoke and not model_path:
        try:
            from speakeasy.config import DEFAULT_MODELS_DIR

            model_path = DEFAULT_MODELS_DIR
        except Exception:
            model_path = ""

    result = run_benchmark(
        device=args.device,
        smoke=args.smoke,
        model_path=model_path,
        iterations=iterations,
        warmup=warmup,
        fixtures_dir=args.fixtures_dir,
    )

    payload = json.dumps(_to_serializable(result), indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
