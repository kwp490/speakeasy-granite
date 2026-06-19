"""Tests for the model_source schema migration in Settings (Phase 3).

Covers §8.3 of the rearchitecture plan: a 0.14.5 ``settings.json`` (bare
``model_path``) migrates to the discriminated ``model_source`` union, offline
custom paths are preserved (the C-4 regression), the legacy mirror is written
for downgrade compatibility, and a forward 0.15 file round-trips.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from speakeasy.config import DEFAULT_MODELS_DIR, Settings


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_legacy_default_path_migrates_to_managed(tmp_path):
    cfg = _write(tmp_path / "settings.json", {"model_path": DEFAULT_MODELS_DIR})
    s = Settings.load(cfg)
    assert s.model_source == {"type": "managed", "path": ""}
    assert s.model_path == DEFAULT_MODELS_DIR


def test_legacy_custom_existing_path_migrates_to_local_dir(tmp_path):
    custom = tmp_path / "models"
    custom.mkdir()
    cfg = _write(tmp_path / "settings.json", {"model_path": str(custom)})
    s = Settings.load(cfg)
    assert s.model_source == {"type": "local_dir", "path": str(custom)}
    assert s.model_path == str(custom)
    assert s.model_location_needs_attention is False


def test_offline_custom_path_is_preserved_not_reset(tmp_path):
    # Regression for C-4: an offline UNC / removable path must NOT be erased.
    offline = r"\\nas01\share\speakeasy-models"
    cfg = _write(tmp_path / "settings.json", {"model_path": offline})
    s = Settings.load(cfg)
    assert s.model_path == offline
    assert s.model_source == {"type": "local_dir", "path": offline}
    assert s.model_location_needs_attention is True


def test_explicit_model_source_is_used(tmp_path):
    custom = tmp_path / "weights"
    custom.mkdir()
    cfg = _write(
        tmp_path / "settings.json",
        {
            "model_path": DEFAULT_MODELS_DIR,
            "model_source": {"type": "local_dir", "path": str(custom)},
        },
    )
    s = Settings.load(cfg)
    assert s.model_source == {"type": "local_dir", "path": str(custom)}
    # legacy mirror follows the source, overriding the stale model_path
    assert s.model_path == str(custom)


def test_remote_source_mirrors_managed_default_for_downgrade(tmp_path):
    cfg = _write(
        tmp_path / "settings.json",
        {"model_source": {"type": "remote", "url": "http://10.0.0.42:8765"}},
    )
    s = Settings.load(cfg)
    assert s.model_source["type"] == "remote"
    assert s.model_source["url"] == "http://10.0.0.42:8765"
    assert "token" not in s.model_source
    # legacy model_path mirror points at the managed default
    assert s.model_path == DEFAULT_MODELS_DIR


def test_invalid_model_source_falls_back_to_managed(tmp_path):
    cfg = _write(
        tmp_path / "settings.json",
        {"model_source": {"type": "ftp", "path": "x"}},
    )
    s = Settings.load(cfg)
    assert s.model_source == {"type": "managed", "path": ""}
    assert s.model_path == DEFAULT_MODELS_DIR


def test_save_round_trip_writes_legacy_mirror(tmp_path):
    custom = tmp_path / "models"
    custom.mkdir()
    s = Settings()
    s.model_source = {"type": "local_dir", "path": str(custom)}
    s.validate()
    out = tmp_path / "out.json"
    s.save(out)

    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["model_source"] == {"type": "local_dir", "path": str(custom)}
    assert raw["model_path"] == str(custom)  # mirror present for 0.14.x downgrade

    reloaded = Settings.load(out)
    assert reloaded.model_source == s.model_source
    assert reloaded.model_path == str(custom)


def test_needs_attention_is_not_persisted(tmp_path):
    s = Settings()
    s.model_source = {"type": "local_dir", "path": r"\\nas01\share\x"}
    s.validate()
    assert s.model_location_needs_attention is True
    out = tmp_path / "out.json"
    s.save(out)
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert "model_location_needs_attention" not in raw


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
