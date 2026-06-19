"""Targeted coverage for services error/edge paths (plan §12.1 Phase 8).

These exercise the branches the happy-path suites in ``test_serve.py`` and
``test_remote_client.py`` do not reach: the ``serve()`` bootstrap and its
failure exit codes, the server-side 4xx/5xx handlers, the in-process
source/probe edge cases, and the remote keyring helpers.
"""

from __future__ import annotations

import json
import sys
import threading
import types
import urllib.error
import urllib.request

import numpy as np
import pytest

from speakeasy.core import wire
from speakeasy.core.contract import TranscriptionOptions
from speakeasy.core.errors import EngineError, ModelNotConfigured
from speakeasy.core.model_source import ManagedSource, RemoteSource
from speakeasy.engines.fake import FakeEngine
from speakeasy.services import remote_client as rc
from speakeasy.services import server as server_mod
from speakeasy.services.inprocess import InProcessEngineService


# ── serve() bootstrap ────────────────────────────────────────────────────────


class _FakeServer:
    def __init__(self) -> None:
        self.server_address = ("127.0.0.1", 18765)
        self.shutdown_called = False
        self.closed = False

    def serve_forever(self) -> None:
        raise KeyboardInterrupt

    def shutdown(self) -> None:
        self.shutdown_called = True

    def server_close(self) -> None:
        self.closed = True


def test_serve_happy_path_returns_0(monkeypatch):
    svc = InProcessEngineService(FakeEngine())
    monkeypatch.setattr(
        "speakeasy.services.provisioning.ensure_model", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "speakeasy.engines.registry.create_service", lambda engine: svc
    )
    fake = _FakeServer()
    monkeypatch.setattr(server_mod, "create_server", lambda *a, **k: fake)

    code = server_mod.serve(
        host="127.0.0.1", port=0, device="cpu", engine="fake", model_dir="/tmp/m"
    )

    assert code == 0
    assert fake.shutdown_called and fake.closed


def test_serve_provisioning_failure_returns_1(monkeypatch):
    def boom(*a, **k):
        raise EngineError("provision fail")

    monkeypatch.setattr("speakeasy.services.provisioning.ensure_model", boom)
    assert server_mod.serve(engine="fake", model_dir="/tmp/m") == 1


def test_serve_load_failure_returns_1(monkeypatch):
    class _BadLoad(InProcessEngineService):
        def load(self, source, device):  # type: ignore[override]
            raise EngineError("load fail")

    svc = _BadLoad(FakeEngine())
    monkeypatch.setattr(
        "speakeasy.services.provisioning.ensure_model", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "speakeasy.engines.registry.create_service", lambda engine: svc
    )
    assert server_mod.serve(engine="fake", model_dir="/tmp/m") == 1


def test_serve_bind_failure_returns_2(monkeypatch):
    svc = InProcessEngineService(FakeEngine())
    monkeypatch.setattr(
        "speakeasy.services.provisioning.ensure_model", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "speakeasy.engines.registry.create_service", lambda engine: svc
    )

    def bad_create(*a, **k):
        raise ValueError("unsafe bind")

    monkeypatch.setattr(server_mod, "create_server", bad_create)
    assert server_mod.serve(engine="fake", model_dir="/tmp/m") == 2


# ── Server-side error handlers ───────────────────────────────────────────────


@pytest.fixture
def serve_stub():
    started: list = []

    def start(service, token=None):
        srv = server_mod.create_server(service, "127.0.0.1", 0, token=token)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        started.append((srv, thread))
        _, port = srv.server_address[:2]
        return f"http://127.0.0.1:{port}"

    yield start

    for srv, thread in started:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def _post(url, data, *, options=None, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if options is not None:
        headers["X-SpeakEasy-Options"] = (
            options if isinstance(options, str) else json.dumps(options)
        )
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


class _HealthBroken:
    def health(self):
        raise RuntimeError("boom")

    def descriptor(self):  # pragma: no cover - never reached
        raise AssertionError


class _CapsBroken:
    def capabilities(self):
        raise RuntimeError("boom")


class _TranscribeEngineError:
    def transcribe(self, audio, options):
        raise EngineError("engine sad")


class _TranscribeGeneric:
    def transcribe(self, audio, options):
        raise RuntimeError("kaboom")


def test_health_handler_returns_500(serve_stub):
    url = serve_stub(_HealthBroken())
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{url}/v1/health")
    assert exc.value.code == 500


def test_capabilities_handler_returns_500(serve_stub):
    url = serve_stub(_CapsBroken())
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{url}/v1/capabilities")
    assert exc.value.code == 500


def test_transcribe_engine_error_returns_409(serve_stub):
    url = serve_stub(_TranscribeEngineError())
    wav = wire.audio_to_wav_bytes(np.zeros(16000, dtype=np.float32))
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{url}/v1/transcribe", wav, options=wire.options_to_dict(TranscriptionOptions()))
    assert exc.value.code == 409


def test_transcribe_generic_error_returns_500(serve_stub):
    url = serve_stub(_TranscribeGeneric())
    wav = wire.audio_to_wav_bytes(np.zeros(16000, dtype=np.float32))
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{url}/v1/transcribe", wav, options=wire.options_to_dict(TranscriptionOptions()))
    assert exc.value.code == 500


def test_transcribe_bad_options_header_returns_400(serve_stub):
    svc = InProcessEngineService(FakeEngine())
    svc.load(ManagedSource(path="/srv"), "cpu")
    url = serve_stub(svc)
    wav = wire.audio_to_wav_bytes(np.zeros(16000, dtype=np.float32))
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{url}/v1/transcribe", wav, options="{not json")
    assert exc.value.code == 400


def test_transcribe_malformed_wav_returns_400(serve_stub):
    svc = InProcessEngineService(FakeEngine())
    svc.load(ManagedSource(path="/srv"), "cpu")
    url = serve_stub(svc)
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{url}/v1/transcribe", b"not a wav file at all")
    assert exc.value.code == 400


def test_transcribe_wrong_sample_rate_returns_400(serve_stub):
    svc = InProcessEngineService(FakeEngine())
    svc.load(ManagedSource(path="/srv"), "cpu")
    url = serve_stub(svc)
    wav = wire.audio_to_wav_bytes(np.zeros(8000, dtype=np.float32), sample_rate=8000)
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{url}/v1/transcribe", wav, options=wire.options_to_dict(TranscriptionOptions()))
    assert exc.value.code == 400


def test_post_unknown_path_returns_404(serve_stub):
    url = serve_stub(InProcessEngineService(FakeEngine()))
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{url}/v1/nope", b"x")
    assert exc.value.code == 404


def test_post_missing_token_returns_401(serve_stub):
    url = serve_stub(InProcessEngineService(FakeEngine()), token="secret")
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{url}/v1/transcribe", b"x")
    assert exc.value.code == 401


# ── InProcessEngineService edge cases ────────────────────────────────────────


def test_inprocess_rejects_remote_source():
    svc = InProcessEngineService(FakeEngine())
    with pytest.raises(EngineError):
        svc.load(RemoteSource(url="http://example", timeout_s=1.0), "cpu")


def test_inprocess_rejects_empty_path():
    svc = InProcessEngineService(FakeEngine())
    with pytest.raises(ModelNotConfigured):
        svc.load(ManagedSource(path=""), "cpu")


def test_inprocess_rejects_unknown_source_type():
    svc = InProcessEngineService(FakeEngine())

    class _Weird:
        pass

    with pytest.raises(TypeError):
        svc.load(_Weird(), "cpu")  # type: ignore[arg-type]


def test_probe_device_non_cuda_delegates_to_health():
    svc = InProcessEngineService(FakeEngine())
    svc.load(ManagedSource(path="/srv"), "cpu")
    report = svc.probe_device()
    assert report.status in ("ok", "not_loaded")


def test_probe_device_cuda_success(monkeypatch):
    svc = InProcessEngineService(FakeEngine())
    svc.load(ManagedSource(path="/srv"), "cpu")
    monkeypatch.setattr(type(svc._engine), "actual_device", "cuda:0", raising=False)
    fake_torch = types.SimpleNamespace(zeros=lambda *a, **k: object())
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert svc.probe_device().status == "ok"


def test_probe_device_cuda_lost(monkeypatch):
    svc = InProcessEngineService(FakeEngine())
    svc.load(ManagedSource(path="/srv"), "cpu")
    monkeypatch.setattr(type(svc._engine), "actual_device", "cuda:0", raising=False)

    def boom(*a, **k):
        raise RuntimeError("CUDA context gone")

    fake_torch = types.SimpleNamespace(zeros=boom)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert svc.probe_device().status == "device_lost"


# ── Remote keyring helpers ───────────────────────────────────────────────────


def test_keyring_helpers_roundtrip(monkeypatch):
    store: dict = {}
    fake_keyring = types.SimpleNamespace(
        get_password=lambda s, u: store.get((s, u)),
        set_password=lambda s, u, p: store.__setitem__((s, u), p),
        delete_password=lambda s, u: store.pop((s, u), None),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    rc.save_remote_token("tok-123")
    assert rc.load_remote_token() == "tok-123"
    rc.delete_remote_token()
    assert rc.load_remote_token() == ""


def test_keyring_helpers_tolerate_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no keyring backend")

    fake_keyring = types.SimpleNamespace(
        get_password=boom, set_password=boom, delete_password=boom
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    assert rc.load_remote_token() == ""
    rc.save_remote_token("x")  # must not raise
    rc.delete_remote_token()  # must not raise


def test_remote_descriptor_tolerates_unreachable_server():
    client = rc.RemoteEngineClient(
        RemoteSource(url="http://127.0.0.1:1", timeout_s=1.0), token="t"
    )
    descriptor = client.descriptor()
    assert descriptor.is_remote is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
