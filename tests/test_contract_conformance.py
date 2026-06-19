"""Contract conformance suite.

Parametrized over every ``TranscriptionService`` implementation so each one is
held to the same behavioral contract.  Phase 1 shipped the in-process leg
(``InProcessEngineService`` wrapping ``FakeEngine``); Phase 4 adds the remote
leg (``RemoteEngineClient`` talking real HTTP to ``services.server`` over
loopback, also backed by ``FakeEngine``).

Tests that exercise behavior that is *inherently* in-process (empty-path
validation, rejecting a ``RemoteSource``, pre-load health state) stay on the
in-process factory only; everything else runs against both legs.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from speakeasy.core.contract import (
    EngineCapabilities,
    EngineDescriptor,
    EngineStats,
    HealthReport,
    LoadReport,
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptionService,
)
from speakeasy.core.errors import EngineError, ModelNotConfigured
from speakeasy.core.model_source import (
    LocalDirSource,
    ManagedSource,
    RemoteSource,
)
from speakeasy.engines.fake import FakeEngine
from speakeasy.services.inprocess import InProcessEngineService
from speakeasy.services.remote_client import RemoteEngineClient
from speakeasy.services.server import create_server

_TEST_TOKEN = "conformance-token"


def _make_inprocess(**engine_kwargs) -> TranscriptionService:
    return InProcessEngineService(FakeEngine(**engine_kwargs))


@pytest.fixture
def remote_factory():
    """A factory that spins up a loopback server + client per call.

    The server's backing engine is pre-loaded so the remote ``transcribe`` path
    works; created servers are torn down at the end of the test.
    """
    created: list = []

    def make(**engine_kwargs) -> TranscriptionService:
        backing = InProcessEngineService(FakeEngine(**engine_kwargs))
        backing.load(ManagedSource(path="/srv"), "cpu")
        server = create_server(backing, "127.0.0.1", 0, token=_TEST_TOKEN)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        created.append((server, thread))
        _, port = server.server_address[:2]
        client = RemoteEngineClient(
            RemoteSource(url=f"http://127.0.0.1:{port}"),
            token=_TEST_TOKEN,
        )
        return client

    yield make

    for server, thread in created:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(params=["inprocess_fake", "remote_fake"])
def service_factory(request, remote_factory):
    if request.param == "inprocess_fake":
        return _make_inprocess
    return remote_factory


def _audio(n=16000):
    return np.zeros(n, dtype=np.float32)


# ── Shared behavior (both legs) ──────────────────────────────────────────────


def test_satisfies_protocol(service_factory):
    service = service_factory()
    assert isinstance(service, TranscriptionService)


def test_descriptor(service_factory):
    desc = service_factory().descriptor()
    assert isinstance(desc, EngineDescriptor)
    assert desc.name
    assert desc.version


def test_capabilities(service_factory):
    caps = service_factory().capabilities()
    assert isinstance(caps, EngineCapabilities)
    assert caps.languages


def test_load_unload_lifecycle(service_factory):
    service = service_factory()
    assert service.is_loaded is False

    report = service.load(LocalDirSource(path="/dummy"), device="cpu")
    assert isinstance(report, LoadReport)
    assert service.is_loaded is True

    service.unload()
    assert service.is_loaded is False


def test_transcribe_returns_result(service_factory):
    service = service_factory(transcript="hello world")
    service.load(ManagedSource(path="/dummy"), device="cpu")
    result = service.transcribe(_audio(), TranscriptionOptions())
    assert isinstance(result, TranscriptionResult)
    assert result.text == "hello world"
    assert result.audio_s == pytest.approx(1.0, abs=1e-3)


def test_stats_reflect_inference(service_factory):
    service = service_factory(tokens_per_call=3)
    service.load(LocalDirSource(path="/dummy"), device="cpu")
    service.transcribe(_audio(), TranscriptionOptions())
    stats = service.stats()
    assert isinstance(stats, EngineStats)
    assert stats.total_tokens == 3
    assert stats.inference_count == 1


def test_health_after_load(service_factory):
    service = service_factory()
    service.load(LocalDirSource(path="/dummy"), device="cpu")
    health = service.health()
    assert isinstance(health, HealthReport)
    assert health.model_loaded is True


def test_transcribe_options_select_task(service_factory):
    service = service_factory()
    service.load(LocalDirSource(path="/dummy"), device="cpu")
    result = service.transcribe(
        _audio(), TranscriptionOptions(task="translate", translation_target="French")
    )
    assert "translate" in result.text


# ── In-process-only behavior ─────────────────────────────────────────────────


def test_health_before_load_inprocess():
    service = _make_inprocess()
    assert service.health().model_loaded is False


def test_error_taxonomy_on_load_inprocess():
    # Empty path → ModelNotConfigured (an EngineError subclass).
    service = _make_inprocess()
    with pytest.raises(ModelNotConfigured):
        service.load(LocalDirSource(path=""), device="cpu")


def test_remote_source_rejected_inprocess():
    service = _make_inprocess()
    with pytest.raises(EngineError):
        service.load(RemoteSource(url="http://host:8765"), device="cpu")
