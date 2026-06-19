"""Wire (de)serialization for the remote transcription protocol.

Both :mod:`speakeasy.services.server` and
:mod:`speakeasy.services.remote_client` use these helpers so the encoding lives
in exactly one place.  Audio crosses the wire as a 16 kHz mono PCM16 WAV
container (curl-debuggable, content-typed); the contract dataclasses round-trip
as plain JSON.

This module is part of ``core`` and therefore must stay free of
torch/transformers/librosa/Qt imports.  Only :mod:`numpy` (already a UI
dependency) and the standard library are used.
"""

from __future__ import annotations

import io
import wave

import numpy as np

from .contract import (
    EngineCapabilities,
    EngineStats,
    HealthReport,
    LoadReport,
    TranscriptionOptions,
    TranscriptionResult,
)

TARGET_SR = 16000


# ── Audio <-> WAV ────────────────────────────────────────────────────────────


def audio_to_wav_bytes(audio_16k: np.ndarray, sample_rate: int = TARGET_SR) -> bytes:
    """Encode a mono float32 waveform as a PCM16 WAV byte string."""
    audio = np.asarray(audio_16k, dtype=np.float32).reshape(-1)
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = np.round(clipped * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm16.tobytes())
    return buf.getvalue()


def wav_bytes_to_audio(data: bytes) -> tuple[np.ndarray, int]:
    """Decode a PCM16 WAV byte string into ``(mono float32, sample_rate)``.

    Multi-channel input is down-mixed to mono.  Raises ``ValueError`` for a
    non-PCM16 container.
    """
    with wave.open(io.BytesIO(data), "rb") as wav:
        n_channels = wav.getnchannels()
        sampwidth = wav.getsampwidth()
        framerate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if sampwidth != 2:
        raise ValueError(f"Expected 16-bit PCM WAV, got sample width {sampwidth}")
    pcm = np.frombuffer(frames, dtype="<i2")
    if n_channels > 1:
        pcm = pcm.reshape(-1, n_channels).mean(axis=1)
    audio = (pcm.astype(np.float32) / 32767.0).astype(np.float32)
    return audio, int(framerate)


# ── TranscriptionOptions ─────────────────────────────────────────────────────


def options_to_dict(options: TranscriptionOptions) -> dict:
    return {
        "task": options.task,
        "language": options.language,
        "translation_target": options.translation_target,
        "keyword_bias": options.keyword_bias,
        "punctuation": options.punctuation,
        "formatting_style": options.formatting_style,
        "timeout_s": options.timeout_s,
    }


def options_from_dict(data: dict) -> TranscriptionOptions:
    defaults = TranscriptionOptions()
    return TranscriptionOptions(
        task=str(data.get("task", defaults.task)),
        language=str(data.get("language", defaults.language)),
        translation_target=str(
            data.get("translation_target", defaults.translation_target)
        ),
        keyword_bias=str(data.get("keyword_bias", defaults.keyword_bias)),
        punctuation=bool(data.get("punctuation", defaults.punctuation)),
        formatting_style=str(
            data.get("formatting_style", defaults.formatting_style)
        ),
        timeout_s=float(data.get("timeout_s", defaults.timeout_s)),
    )


# ── TranscriptionResult ──────────────────────────────────────────────────────


def result_to_dict(result: TranscriptionResult) -> dict:
    return {
        "text": result.text,
        "audio_s": result.audio_s,
        "inference_s": result.inference_s,
        "tokens_generated": result.tokens_generated,
        "realtime_factor": result.realtime_factor,
        "device": result.device,
    }


def result_from_dict(data: dict) -> TranscriptionResult:
    defaults = TranscriptionResult(text="")
    return TranscriptionResult(
        text=str(data.get("text", "")),
        audio_s=float(data.get("audio_s", defaults.audio_s)),
        inference_s=float(data.get("inference_s", defaults.inference_s)),
        tokens_generated=int(data.get("tokens_generated", defaults.tokens_generated)),
        realtime_factor=float(data.get("realtime_factor", defaults.realtime_factor)),
        device=str(data.get("device", defaults.device)),
    )


# ── EngineCapabilities ───────────────────────────────────────────────────────


def capabilities_to_dict(caps: EngineCapabilities) -> dict:
    return {
        "languages": list(caps.languages),
        "supports_translation": caps.supports_translation,
        "translation_targets": list(caps.translation_targets),
        "supports_keyword_bias": caps.supports_keyword_bias,
        "supports_timestamps": caps.supports_timestamps,
        "supports_streaming": caps.supports_streaming,
        "formatting_styles": list(caps.formatting_styles),
        "devices": list(caps.devices),
        "max_clip_seconds": caps.max_clip_seconds,
        "is_remote": caps.is_remote,
    }


def capabilities_from_dict(data: dict) -> EngineCapabilities:
    return EngineCapabilities(
        languages=tuple(data.get("languages", ())),
        supports_translation=bool(data.get("supports_translation", False)),
        translation_targets=tuple(data.get("translation_targets", ())),
        supports_keyword_bias=bool(data.get("supports_keyword_bias", False)),
        supports_timestamps=bool(data.get("supports_timestamps", False)),
        supports_streaming=bool(data.get("supports_streaming", False)),
        formatting_styles=tuple(data.get("formatting_styles", ())),
        devices=tuple(data.get("devices", ())),
        max_clip_seconds=float(data.get("max_clip_seconds", 0.0)),
        is_remote=bool(data.get("is_remote", False)),
    )


# ── EngineStats ──────────────────────────────────────────────────────────────


def stats_to_dict(stats: EngineStats) -> dict:
    return {
        "tokens_per_second": stats.tokens_per_second,
        "total_tokens": stats.total_tokens,
        "total_audio_seconds": stats.total_audio_seconds,
        "realtime_factor": stats.realtime_factor,
        "inference_count": stats.inference_count,
    }


def stats_from_dict(data: dict) -> EngineStats:
    defaults = EngineStats()
    return EngineStats(
        tokens_per_second=float(data.get("tokens_per_second", defaults.tokens_per_second)),
        total_tokens=int(data.get("total_tokens", defaults.total_tokens)),
        total_audio_seconds=float(
            data.get("total_audio_seconds", defaults.total_audio_seconds)
        ),
        realtime_factor=float(data.get("realtime_factor", defaults.realtime_factor)),
        inference_count=int(data.get("inference_count", defaults.inference_count)),
    )


def load_report_to_dict(report: LoadReport) -> dict:
    return {
        "device": report.device,
        "load_seconds": report.load_seconds,
        "vram_estimate_gb": report.vram_estimate_gb,
        "max_clip_seconds": report.max_clip_seconds,
    }


def health_to_dict(report: HealthReport) -> dict:
    return {
        "status": report.status,
        "detail": report.detail,
        "model_loaded": report.model_loaded,
        "device": report.device,
    }
