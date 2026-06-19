"""Tests for ``RemoteEngineClient`` against a real loopback server.

Each test spins up ``services.server`` wrapping an ``InProcessEngineService``
over a ``FakeEngine`` on ``127.0.0.1:0`` and drives it through the client.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from speakeasy.core.errors import (
    RemoteAuthFailed,
    RemoteUnreachable,
    RemoteVersionMismatch,
)
from speakeasy.core.contract import TranscriptionOptions, TranscriptionService
from speakeasy.core.model_source import ManagedSource, RemoteSource
from speakeasy.engines.fake import FakeEngine
from speakeasy.services.inprocess import InProcessEngineService
from speakeasy.services.remote_client import RemoteEngineClient
from speakeasy.services import server as server_mod

_TOKEN = "secret-token"


@pytest.fixture
def running_server():
    servers: list = []

    def start(*, token=_TOKEN, load=True, **engine_kwargs):
        backing = InProcessEngineService(FakeEngine(**engine_kwargs))
        if load:
            backing.load(ManagedSource(path="/srv"), "cpu")
        srv = server_mod.create_server(backing, "127.0.0.1", 0, token=token)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        servers.append((srv, thread))
        _, port = srv.server_address[:2]
        return f"http://127.0.0.1:{port}", backing

    yield start

    for srv, thread in servers:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _client(url, token=_TOKEN, **source_kwargs):
    return RemoteEngineClient(RemoteSource(url=url, **source_kwargs), token=token)


def test_client_satisfies_protocol(running_server):
    url, _ = running_server()
    assert isinstance(_client(url), TranscriptionService)


def test_health_ok(running_server):
    url, _ = running_server()
    client = _client(url)
    health = client.health()
    assert health.status == "ok"
    assert health.model_loaded is True


def test_load_reports_device(running_server):
    url, _ = running_server()
    client = _client(url)
    report = client.load(ManagedSource(path="/dummy"), "cpu")
    assert report.device == "cpu"
    assert client.is_loaded is True
    client.unload()
    assert client.is_loaded is False


def test_capabilities_round_trip(running_server):
    url, _ = running_server()
    caps = _client(url).capabilities()
    assert "en" in caps.languages
    assert caps.supports_translation is True


def test_transcribe_round_trip(running_server):
    url, _ = running_server(transcript="remote hello")
    client = _client(url)
    client.load(ManagedSource(path="/dummy"), "cpu")
    audio = np.zeros(16000, dtype=np.float32)
    result = client.transcribe(audio, TranscriptionOptions())
    assert result.text == "remote hello"
    assert result.audio_s == pytest.approx(1.0, abs=1e-3)


def test_transcribe_preserves_audio_length(running_server):
    url, _ = running_server()
    client = _client(url)
    audio = np.zeros(8000, dtype=np.float32)  # 0.5 s
    result = client.transcribe(audio, TranscriptionOptions())
    assert result.audio_s == pytest.approx(0.5, abs=1e-3)


def test_options_task_forwarded(running_server):
    url, _ = running_server()
    client = _client(url)
    result = client.transcribe(
        np.zeros(16000, dtype=np.float32),
        TranscriptionOptions(task="translate"),
    )
    assert "translate" in result.text


def test_stats_accumulate(running_server):
    url, _ = running_server(tokens_per_call=5)
    client = _client(url)
    client.transcribe(np.zeros(16000, dtype=np.float32), TranscriptionOptions())
    client.transcribe(np.zeros(16000, dtype=np.float32), TranscriptionOptions())
    stats = client.stats()
    assert stats.total_tokens == 10
    assert stats.inference_count == 2


def test_bearer_token_required(running_server):
    url, _ = running_server()
    # Wrong token → 401 → RemoteAuthFailed.
    client = _client(url, token="wrong-token")
    with pytest.raises(RemoteAuthFailed):
        client.health()


def test_missing_token_rejected(running_server):
    url, _ = running_server()
    client = _client(url, token=None)
    with pytest.raises(RemoteAuthFailed):
        client.health()


def _closed_port() -> int:
    """Return a port number that is (almost certainly) not accepting connections."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_unreachable_endpoint():
    client = RemoteEngineClient(
        RemoteSource(url=f"http://127.0.0.1:{_closed_port()}", timeout_s=0.5),
        token=None,
    )
    with pytest.raises(RemoteUnreachable):
        client.test_connection()


def test_health_unreachable_returns_status():
    client = RemoteEngineClient(
        RemoteSource(url=f"http://127.0.0.1:{_closed_port()}", timeout_s=0.5),
        token=None,
    )
    # test_connection raises, but health() swallows into a status report.
    report = client.health()
    assert report.status == "unreachable"
    assert report.model_loaded is False


def test_contract_version_mismatch(running_server, monkeypatch):
    url, _ = running_server()
    # Make the server advertise a future contract version.
    monkeypatch.setattr(server_mod, "CONTRACT_VERSION", 999)
    client = _client(url)
    with pytest.raises(RemoteVersionMismatch):
        client.health()


def test_server_500_surfaces_as_unreachable_with_detail():
    """A non-auth server error must map to RemoteUnreachable carrying the
    server's error detail (exercises the HTTPError detail path)."""

    class _BrokenService:
        def health(self):
            raise RuntimeError("server exploded")

        def descriptor(self):  # pragma: no cover - never reached
            raise AssertionError

    srv = server_mod.create_server(_BrokenService(), "127.0.0.1", 0, token=None)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        _, port = srv.server_address[:2]
        client = RemoteEngineClient(
            RemoteSource(url=f"http://127.0.0.1:{port}", timeout_s=2.0), token=None
        )
        with pytest.raises(RemoteUnreachable):
            client.test_connection()
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_descriptor_marks_remote(running_server):
    url, _ = running_server()
    desc = _client(url).descriptor()
    assert desc.is_remote is True
    assert desc.name == "fake"


def test_verify_tls_flag_stored():
    client = RemoteEngineClient(
        RemoteSource(url="https://host:8765", verify_tls=False), token="t"
    )
    assert client._verify_tls is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
