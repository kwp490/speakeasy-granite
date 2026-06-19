"""Tests for the FakeEngine deterministic test double."""

from __future__ import annotations

import numpy as np
import pytest

from speakeasy.core.contract import TranscriptionOptions
from speakeasy.core.model_source import LocalDirSource
from speakeasy.engines.fake import FakeEngine
from speakeasy.services.inprocess import InProcessEngineService


def _audio(n=16000):
    return np.zeros(n, dtype=np.float32)


def test_not_loaded_initially():
    engine = FakeEngine()
    assert engine.is_loaded is False
    assert engine.name == "fake"


def test_load_sets_loaded():
    engine = FakeEngine()
    engine.load("/dummy", device="cpu")
    assert engine.is_loaded is True


def test_transcribe_requires_load():
    engine = FakeEngine()
    with pytest.raises(RuntimeError):
        engine.transcribe(_audio())


def test_transcribe_is_deterministic():
    engine = FakeEngine()
    engine.load("/dummy")
    a = engine.transcribe(_audio(8000), language="en")
    b = engine.transcribe(_audio(8000), language="en")
    assert a == b


def test_transcribe_uses_configured_transcript():
    engine = FakeEngine(transcript="hello world")
    engine.load("/dummy")
    assert engine.transcribe(_audio()) == "hello world"


def test_transcribe_empty_audio_returns_empty():
    engine = FakeEngine()
    engine.load("/dummy")
    assert engine.transcribe(np.array([], dtype=np.float32)) == ""


def test_translate_task_changes_output():
    service = InProcessEngineService(FakeEngine())
    service.load(LocalDirSource(path="/dummy"), "cpu")
    result = service.transcribe(_audio(), TranscriptionOptions(task="translate"))
    assert "translate" in result.text


def test_failure_injection_on_load():
    boom = RuntimeError("no model")
    engine = FakeEngine(fail_on_load=boom)
    with pytest.raises(RuntimeError, match="no model"):
        engine.load("/dummy")


def test_failure_injection_on_transcribe():
    boom = ValueError("bad audio")
    engine = FakeEngine(fail_on_transcribe=boom)
    engine.load("/dummy")
    with pytest.raises(ValueError, match="bad audio"):
        engine.transcribe(_audio())


def test_latency_injection_records_realtime_factor():
    engine = FakeEngine(latency_s=0.01)
    engine.load("/dummy")
    engine.transcribe(_audio(16000))
    tps, total_tokens, total_audio, rtf, seq = engine.token_stats
    assert seq == 1
    assert total_tokens > 0
    assert total_audio == pytest.approx(1.0, abs=0.01)
    assert rtf > 0


def test_token_stats_accumulate():
    engine = FakeEngine(tokens_per_call=5)
    engine.load("/dummy")
    engine.transcribe(_audio())
    engine.transcribe(_audio())
    _, total_tokens, _, _, seq = engine.token_stats
    assert total_tokens == 10
    assert seq == 2


def test_capabilities_shape():
    caps = FakeEngine().capabilities()
    assert caps.languages
    assert caps.is_remote is False
    assert caps.devices == ("cpu",)
