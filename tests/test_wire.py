"""Round-trip tests for the remote wire (de)serialization helpers."""

from __future__ import annotations

import numpy as np
import pytest

from speakeasy.core import wire
from speakeasy.core.contract import (
    EngineCapabilities,
    EngineStats,
    TranscriptionOptions,
    TranscriptionResult,
)


def test_wav_round_trip_preserves_length_and_rate():
    audio = np.zeros(12345, dtype=np.float32)
    data = wire.audio_to_wav_bytes(audio)
    decoded, sr = wire.wav_bytes_to_audio(data)
    assert sr == wire.TARGET_SR
    assert len(decoded) == len(audio)
    assert decoded.dtype == np.float32


def test_wav_round_trip_amplitude_within_tolerance():
    t = np.linspace(0, 1, wire.TARGET_SR, endpoint=False, dtype=np.float32)
    audio = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    decoded, _ = wire.wav_bytes_to_audio(wire.audio_to_wav_bytes(audio))
    # PCM16 quantization error is bounded by ~1/32767.
    assert np.max(np.abs(decoded - audio)) < 1e-3


def test_wav_clips_out_of_range():
    audio = np.array([2.0, -2.0, 0.0], dtype=np.float32)
    decoded, _ = wire.wav_bytes_to_audio(wire.audio_to_wav_bytes(audio))
    assert decoded[0] == pytest.approx(1.0, abs=1e-3)
    assert decoded[1] == pytest.approx(-1.0, abs=1e-3)


def test_options_round_trip():
    opts = TranscriptionOptions(
        task="translate",
        language="fr",
        translation_target="English",
        keyword_bias="SpeakEasy, Granite",
        punctuation=False,
        formatting_style="plain_text",
        timeout_s=12.5,
    )
    assert wire.options_from_dict(wire.options_to_dict(opts)) == opts


def test_result_round_trip():
    result = TranscriptionResult(
        text="hello",
        audio_s=1.5,
        inference_s=0.3,
        tokens_generated=7,
        realtime_factor=5.0,
        device="cuda",
    )
    assert wire.result_from_dict(wire.result_to_dict(result)) == result


def test_capabilities_round_trip():
    caps = EngineCapabilities(
        languages=("auto", "en", "fr"),
        supports_translation=True,
        translation_targets=("English",),
        supports_keyword_bias=True,
        supports_timestamps=False,
        supports_streaming=False,
        formatting_styles=("sentence_case",),
        devices=("cuda", "cpu"),
        max_clip_seconds=30.0,
        is_remote=False,
    )
    assert wire.capabilities_from_dict(wire.capabilities_to_dict(caps)) == caps


def test_stats_round_trip():
    stats = EngineStats(
        tokens_per_second=12.0,
        total_tokens=100,
        total_audio_seconds=20.0,
        realtime_factor=5.0,
        inference_count=4,
    )
    assert wire.stats_from_dict(wire.stats_to_dict(stats)) == stats


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
