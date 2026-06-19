"""Tests for the discriminated model-source schema (core.model_source)."""

from __future__ import annotations

import pytest

from speakeasy.core import model_source as ms


def test_parse_managed_roundtrip():
    src = ms.parse({"type": "managed", "path": r"C:\ProgramData\models"})
    assert isinstance(src, ms.ManagedSource)
    assert src.path == r"C:\ProgramData\models"
    assert ms.to_dict(src) == {"type": "managed", "path": r"C:\ProgramData\models"}


def test_parse_local_dir_roundtrip():
    src = ms.parse({"type": "local_dir", "path": r"D:\models"})
    assert isinstance(src, ms.LocalDirSource)
    assert src.path == r"D:\models"
    assert ms.to_dict(src) == {"type": "local_dir", "path": r"D:\models"}


def test_parse_remote_roundtrip():
    src = ms.parse(
        {
            "type": "remote",
            "url": "http://10.0.0.42:8765",
            "verify_tls": False,
            "timeout_s": 5,
        }
    )
    assert isinstance(src, ms.RemoteSource)
    assert src.url == "http://10.0.0.42:8765"
    assert src.verify_tls is False
    assert src.timeout_s == 5.0
    assert src.auth_token_ref == "keyring"

    out = ms.to_dict(src)
    assert out["type"] == "remote"
    assert out["url"] == "http://10.0.0.42:8765"
    assert out["auth_token_ref"] == "keyring"


def test_remote_source_never_serializes_token():
    # RemoteSource has no token field at all; only a keyring reference.
    src = ms.RemoteSource(url="https://host:8765")
    out = ms.to_dict(src)
    assert "token" not in out
    assert "auth_token" not in out
    assert not hasattr(src, "token")


def test_parse_rejects_unknown_type():
    with pytest.raises(ValueError):
        ms.parse({"type": "ftp"})


def test_parse_rejects_non_mapping():
    with pytest.raises(ValueError):
        ms.parse("managed")


@pytest.mark.parametrize("url", ["file:///c:/models", "ftp://host/x", "ws://host", ""])
def test_parse_rejects_non_http_remote_url(url):
    with pytest.raises(ValueError):
        ms.parse({"type": "remote", "url": url})


@pytest.mark.parametrize("url", ["http://host:8765", "https://host:8765/api"])
def test_parse_accepts_http_remote_url(url):
    src = ms.parse({"type": "remote", "url": url})
    assert src.url == url


@pytest.mark.parametrize(
    "path",
    [
        r"\\srv\share\models",
        r"\\?\UNC\srv\share\models",
        "//srv/share/models",
    ],
)
def test_classify_path_detects_unc(path):
    assert ms.classify_path(path) == ms.PATH_UNC


def test_classify_path_long_path_local_prefix_is_not_unc():
    # \\?\C:\ is a long-path *local* drive, not a UNC share.
    result = ms.classify_path(r"\\?\C:\models")
    assert result != ms.PATH_UNC


def test_classify_path_empty():
    assert ms.classify_path("") == ms.PATH_UNKNOWN
    assert ms.classify_path("   ") == ms.PATH_UNKNOWN
