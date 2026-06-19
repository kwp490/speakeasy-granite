"""Tests for speakeasy.services.provisioning (Phase 3).

The engine no longer downloads (coupling problem C-2); provisioning is the
single entry point that checks health and downloads, mapping downloader exit
codes onto the typed error taxonomy.
"""

from __future__ import annotations

import sys
import types

import pytest

from speakeasy.core.errors import (
    ModelAuthRequired,
    ModelFilesMissing,
    ModelNotConfigured,
)
from speakeasy.core.model_source import LocalDirSource, ManagedSource, RemoteSource
from speakeasy.services import provisioning


class _FakeHealth:
    def __init__(self, ready: bool, missing=(), invalid=()):
        self._ready = ready
        self.missing_files = tuple(missing)
        self.invalid_files = tuple(invalid)

    @property
    def ready(self) -> bool:
        return self._ready

    def summary(self) -> str:
        return "ready" if self._ready else "incomplete"


def _install_fake_downloader(monkeypatch, *, health_seq, download_rc=0):
    """Patch speakeasy.model_downloader with a controllable stub."""
    calls = {"download": 0}
    seq = list(health_seq)

    mod = types.ModuleType("speakeasy.model_downloader")
    mod.EXIT_SUCCESS = 0
    mod.EXIT_FAILURE = 1
    mod.EXIT_AUTH_REQUIRED = 2

    def _model_health(engine_name, path):
        return seq.pop(0)

    def _download_model(engine_name, path, **kwargs):
        calls["download"] += 1
        return download_rc

    mod.model_health = _model_health
    mod.download_model = _download_model
    monkeypatch.setitem(sys.modules, "speakeasy.model_downloader", mod)
    return calls


def test_remote_source_raises_not_configured():
    with pytest.raises(ModelNotConfigured):
        provisioning.ensure_model(RemoteSource(url="http://x:8765"))


def test_empty_path_raises_not_configured():
    with pytest.raises(ModelNotConfigured):
        provisioning.ensure_model(ManagedSource(path=""))


def test_already_present_skips_download(monkeypatch):
    calls = _install_fake_downloader(monkeypatch, health_seq=[_FakeHealth(True)])
    health = provisioning.ensure_model(LocalDirSource(path=r"C:\models"))
    assert health.ready
    assert calls["download"] == 0


def test_missing_triggers_download_then_succeeds(monkeypatch):
    calls = _install_fake_downloader(
        monkeypatch,
        health_seq=[_FakeHealth(False, missing=("config.json",)), _FakeHealth(True)],
        download_rc=0,
    )
    health = provisioning.ensure_model(LocalDirSource(path=r"C:\models"))
    assert health.ready
    assert calls["download"] == 1


def test_auth_required_maps_to_model_auth_required(monkeypatch):
    _install_fake_downloader(
        monkeypatch,
        health_seq=[_FakeHealth(False, missing=("config.json",))],
        download_rc=2,
    )
    with pytest.raises(ModelAuthRequired):
        provisioning.ensure_model(LocalDirSource(path=r"C:\models"))


def test_download_failure_maps_to_files_missing(monkeypatch):
    _install_fake_downloader(
        monkeypatch,
        health_seq=[
            _FakeHealth(False, missing=("config.json",)),
            _FakeHealth(False, missing=("config.json",)),
        ],
        download_rc=1,
    )
    with pytest.raises(ModelFilesMissing):
        provisioning.ensure_model(LocalDirSource(path=r"C:\models"))


def test_model_local_path_resolves_managed_and_local():
    assert provisioning.model_local_path(LocalDirSource(path=r"D:\m")) == r"D:\m"
    assert provisioning.model_local_path(ManagedSource(path=r"C:\m")) == r"C:\m"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
