"""Tests for the ``speakeasy serve`` HTTP server (``services.server``).

Covers token generation, bind-safety rules, token enforcement, the raw wire
endpoints, and concurrent-request serialization.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

from speakeasy.core import wire
from speakeasy.core.contract import CONTRACT_VERSION, TranscriptionOptions
from speakeasy.core.model_source import ManagedSource
from speakeasy.engines.fake import FakeEngine
from speakeasy.services.inprocess import InProcessEngineService
from speakeasy.services import server as server_mod

_TOKEN = "serve-token"


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
        return f"http://127.0.0.1:{port}"

    yield start

    for srv, thread in servers:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _get(url, token=_TOKEN):
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


# ── Token generation ─────────────────────────────────────────────────────────


def test_generate_token_is_random_and_nonempty():
    a = server_mod.generate_token()
    b = server_mod.generate_token()
    assert a and b
    assert a != b


# ── Bind safety ──────────────────────────────────────────────────────────────


def test_loopback_bind_allowed_without_token():
    svc = InProcessEngineService(FakeEngine())
    srv = server_mod.create_server(svc, "127.0.0.1", 0)
    srv.server_close()


def test_non_loopback_requires_allow_remote():
    svc = InProcessEngineService(FakeEngine())
    with pytest.raises(ValueError):
        server_mod.create_server(svc, "0.0.0.0", 0, token="t")


def test_non_loopback_requires_token():
    svc = InProcessEngineService(FakeEngine())
    with pytest.raises(ValueError):
        server_mod.create_server(svc, "0.0.0.0", 0, allow_remote=True, token=None)


def test_non_loopback_with_allow_remote_and_token_ok():
    svc = InProcessEngineService(FakeEngine())
    srv = server_mod.create_server(
        svc, "0.0.0.0", 0, allow_remote=True, token="t"
    )
    srv.server_close()


# ── Endpoints ────────────────────────────────────────────────────────────────


def test_health_endpoint(running_server):
    url = running_server()
    status, body = _get(f"{url}/v1/health")
    assert status == 200
    assert body["engine"] == "fake"
    assert body["model_loaded"] is True
    assert body["contract_version"] == CONTRACT_VERSION
    assert "app_version" in body


def test_capabilities_endpoint(running_server):
    url = running_server()
    status, body = _get(f"{url}/v1/capabilities")
    assert status == 200
    assert "en" in body["languages"]


def test_unknown_path_404(running_server):
    url = running_server()
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{url}/v1/nope")
    assert excinfo.value.code == 404


def test_missing_token_401(running_server):
    url = running_server()
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{url}/v1/health", token=None)
    assert excinfo.value.code == 401


def test_wrong_token_401(running_server):
    url = running_server()
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{url}/v1/health", token="nope")
    assert excinfo.value.code == 401


def test_no_token_server_allows_requests(running_server):
    url = running_server(token=None)
    status, body = _get(f"{url}/v1/health", token=None)
    assert status == 200


def test_transcribe_endpoint(running_server):
    url = running_server(transcript="served text")
    wav = wire.audio_to_wav_bytes(np.zeros(16000, dtype=np.float32))
    req = urllib.request.Request(
        f"{url}/v1/transcribe",
        data=wav,
        method="POST",
        headers={
            "Authorization": f"Bearer {_TOKEN}",
            "Content-Type": "audio/wav",
            "X-SpeakEasy-Options": json.dumps(
                wire.options_to_dict(TranscriptionOptions())
            ),
        },
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    assert body["text"] == "served text"
    assert body["audio_s"] == pytest.approx(1.0, abs=1e-3)


def test_transcribe_empty_body_400(running_server):
    url = running_server()
    req = urllib.request.Request(
        f"{url}/v1/transcribe",
        data=b"",
        method="POST",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req, timeout=5)
    assert excinfo.value.code == 400


def test_body_size_cap_rejected():
    svc = InProcessEngineService(FakeEngine())
    svc.load(ManagedSource(path="/srv"), "cpu")
    srv = server_mod.create_server(svc, "127.0.0.1", 0, token=None, max_body_bytes=128)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        _, port = srv.server_address[:2]
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/transcribe",
            data=b"x" * 1024,
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=5)
        assert excinfo.value.code == 413
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_concurrent_requests_serialized(running_server):
    """The single inference lock must keep concurrent requests correct."""
    url = running_server(latency_s=0.02, tokens_per_call=2)
    results: list = []
    errors: list = []

    def worker():
        try:
            status, _ = _get(f"{url}/v1/health")
            results.append(status)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert not errors
    assert results == [200] * 5


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
