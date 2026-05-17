"""Tests for model-presence validation across source and frozen builds.

Ensures that ``model_ready()`` and ``_model_files_exist()`` agree, that
model path resolution respects SPEAKEASY_HOME, and that the engine
registry correctly reports availability based on on-disk model files.
"""

import importlib
import os
import sys
import tempfile
import json
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest import mock

from speakeasy.engine import _model_files_exist, get_available_engines
from speakeasy.model_downloader import GRANITE_REQUIRED_FILES, _ENGINE_REPO_MAP, model_ready


def _write_complete_granite_model(model_root: str | Path) -> Path:
    granite_dir = Path(model_root) / "granite"
    granite_dir.mkdir(parents=True, exist_ok=True)
    for filename in GRANITE_REQUIRED_FILES:
        path = granite_dir / filename
        if filename == "model.safetensors.index.json":
            path.write_text(
                json.dumps(
                    {
                        "weight_map": {
                            "layer.0": "model-00001-of-00003.safetensors",
                            "layer.1": "model-00002-of-00003.safetensors",
                            "layer.2": "model-00003-of-00003.safetensors",
                        }
                    }
                ),
                encoding="utf-8",
            )
        elif filename.endswith(".json"):
            path.write_text("{}", encoding="utf-8")
        else:
            path.write_text("x", encoding="utf-8")
    for shard_name in (
        "model-00001-of-00003.safetensors",
        "model-00002-of-00003.safetensors",
        "model-00003-of-00003.safetensors",
    ):
        (granite_dir / shard_name).write_bytes(b"weights")
    return granite_dir


def _health(ready: bool):
    return SimpleNamespace(ready=ready, summary=lambda: "Granite model test health")


class TestModelReadyAndModelFilesExistAgree(unittest.TestCase):
    """``model_ready()`` and ``_model_files_exist()`` must return the same
    result for every engine in ``_ENGINE_REPO_MAP``."""

    def test_both_true_when_model_health_passes(self):
        for engine_name in _ENGINE_REPO_MAP:
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(engine_name, "granite")
                _write_complete_granite_model(d)
                self.assertTrue(
                    model_ready(engine_name, d),
                    f"model_ready should be True for {engine_name}",
                )
                self.assertTrue(
                    _model_files_exist(engine_name, d),
                    f"_model_files_exist should be True for {engine_name}",
                )

    def test_both_false_when_empty_dir(self):
        for engine_name in _ENGINE_REPO_MAP:
            with tempfile.TemporaryDirectory() as d:
                os.makedirs(os.path.join(d, engine_name))
                self.assertFalse(model_ready(engine_name, d))
                self.assertFalse(_model_files_exist(engine_name, d))

    def test_both_false_when_no_dir(self):
        for engine_name in _ENGINE_REPO_MAP:
            with tempfile.TemporaryDirectory() as d:
                self.assertFalse(model_ready(engine_name, d))
                self.assertFalse(_model_files_exist(engine_name, d))


class TestAvailableEnginesReflectsModelPresence(unittest.TestCase):
    """``get_available_engines()`` must only list engines whose model
    files are actually on disk."""

    def test_empty_when_no_models(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(get_available_engines(d), [])

    def test_granite_listed_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            _write_complete_granite_model(d)
            available = get_available_engines(d)
            self.assertIn("granite", available)

    def test_granite_missing_when_tokenizer_files_missing(self):
        with tempfile.TemporaryDirectory() as d:
            granite_dir = Path(d) / "granite"
            granite_dir.mkdir()
            (granite_dir / "config.json").write_text("{}", encoding="utf-8")
            self.assertNotIn("granite", get_available_engines(d))

    def test_granite_missing_when_no_config(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "granite"))
            self.assertNotIn("granite", get_available_engines(d))


class TestModelPathResolution(unittest.TestCase):
    """Model path must resolve correctly for source and frozen builds."""

    def test_source_mode_speakeasy_home(self):
        """When SPEAKEASY_HOME is set, INSTALL_DIR / 'models' should match."""
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"SPEAKEASY_HOME": d}):
                # Re-import to pick up the env var
                import importlib
                import speakeasy.config as cfg
                importlib.reload(cfg)
                try:
                    expected = Path(d) / "models"
                    self.assertEqual(cfg.DEFAULT_MODELS_DIR, str(expected))
                finally:
                    # Restore so other tests are not affected
                    importlib.reload(cfg)

    def test_frozen_mode_default(self):
        """Without SPEAKEASY_HOME, DEFAULT_MODELS_DIR points to %ProgramData%."""
        with mock.patch.dict(os.environ, {}, clear=False):
            env = os.environ.copy()
            env.pop("SPEAKEASY_HOME", None)
            with mock.patch.dict(os.environ, env, clear=True):
                import importlib
                import speakeasy.config as cfg
                importlib.reload(cfg)
                try:
                    programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
                    expected = str(
                        Path(programdata) / "SpeakEasy AI Granite" / "models"
                    )
                    self.assertEqual(cfg.DEFAULT_MODELS_DIR, expected)
                finally:
                    importlib.reload(cfg)



class TestStartupModelSetup(unittest.TestCase):
    """Frozen startup must launch setup when the installed model is missing."""

    def test_source_startup_does_not_launch_installer(self):
        import speakeasy.__main__ as app_main

        settings = SimpleNamespace(model_path=r"C:\Models")

        with mock.patch.object(app_main.sys, "frozen", False, create=True):
            with mock.patch("speakeasy.model_downloader.model_health", return_value=_health(False)):
                with mock.patch("speakeasy.model_downloader.launch_granite_setup_script") as launch:
                    self.assertTrue(app_main._ensure_startup_model_ready(settings))

        launch.assert_not_called()

    def test_frozen_startup_launches_installer_when_model_missing(self):
        import speakeasy.__main__ as app_main
        from PySide6.QtWidgets import QMessageBox

        settings = SimpleNamespace(model_path=r"C:\Models")

        with mock.patch.object(app_main.sys, "frozen", True, create=True):
            with mock.patch(
                "speakeasy.model_downloader.model_health",
                side_effect=[_health(False), _health(True)],
            ):
                with mock.patch(
                    "speakeasy.model_downloader.launch_granite_setup_script",
                    return_value=33,
                ) as launch:
                    with mock.patch(
                        "PySide6.QtWidgets.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.Ok,
                    ) as question:
                        with mock.patch("PySide6.QtWidgets.QMessageBox.warning") as warning:
                            with mock.patch("PySide6.QtWidgets.QMessageBox.critical") as critical:
                                self.assertTrue(app_main._ensure_startup_model_ready(settings))

        launch.assert_called_once_with(target_dir=settings.model_path)
        question.assert_called_once()
        warning.assert_not_called()
        critical.assert_not_called()

    def test_frozen_startup_shows_error_when_setup_script_missing(self):
        import speakeasy.__main__ as app_main

        settings = SimpleNamespace(model_path=r"C:\Models")

        with mock.patch.object(app_main.sys, "frozen", True, create=True):
            with mock.patch("speakeasy.model_downloader.model_health", return_value=_health(False)):
                with mock.patch(
                    "speakeasy.model_downloader.launch_granite_setup_script",
                    side_effect=FileNotFoundError,
                ):
                    with mock.patch(
                        "speakeasy.model_downloader.get_granite_setup_script_candidates",
                        return_value=(
                            Path(r"C:\Program Files\SpeakEasy AI Granite\granite-model-setup.ps1"),
                            Path(r"C:\Coding_Projects\speakeasy-granite\installer\granite-model-setup.ps1"),
                        ),
                    ):
                        with mock.patch("PySide6.QtWidgets.QMessageBox.critical") as critical:
                            self.assertFalse(app_main._ensure_startup_model_ready(settings))

        critical.assert_called_once()


if __name__ == "__main__":
    unittest.main()


