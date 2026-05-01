"""Tests for the model downloader module."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from speakeasy.model_downloader import (
    GRANITE_REPO_ID,
    EXIT_AUTH_REQUIRED,
    EXIT_FAILURE,
    EXIT_SUCCESS,
    _ENGINE_REPO_MAP,
    _is_gated_repo_error,
    download_model,
    launch_granite_setup_script,
    model_ready,
)


class TestModelConstants(unittest.TestCase):
    """Model constants must be consistent and non-empty."""

    def test_repo_ids_are_valid(self):
        self.assertIn("/", GRANITE_REPO_ID)
        self.assertFalse(GRANITE_REPO_ID.startswith("http"))

    def test_engine_repo_map(self):
        self.assertIn("granite", _ENGINE_REPO_MAP)
        self.assertEqual(_ENGINE_REPO_MAP["granite"], GRANITE_REPO_ID)
        self.assertEqual(len(_ENGINE_REPO_MAP), 1)


class TestModelReady(unittest.TestCase):
    """model_ready must correctly detect present/absent models."""

    def test_ready_when_config_exists(self):
        with tempfile.TemporaryDirectory() as d:
            engine_dir = os.path.join(d, "granite")
            os.makedirs(engine_dir)
            with open(os.path.join(engine_dir, "config.json"), "w") as f:
                f.write("{}")
            self.assertTrue(model_ready("granite", d))

    def test_not_ready_when_no_dir(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(model_ready("granite", d))

    def test_not_ready_when_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "granite"))
            self.assertFalse(model_ready("granite", d))

    def test_ready_for_granite(self):
        with tempfile.TemporaryDirectory() as d:
            engine_dir = os.path.join(d, "granite")
            os.makedirs(engine_dir)
            with open(os.path.join(engine_dir, "config.json"), "w") as f:
                f.write("{}")
            self.assertTrue(model_ready("granite", d))


class TestExitCodeConstants(unittest.TestCase):
    """Exit code constants must have the expected values (installer depends on them)."""

    def test_exit_success(self):
        self.assertEqual(EXIT_SUCCESS, 0)

    def test_exit_failure(self):
        self.assertEqual(EXIT_FAILURE, 1)

    def test_exit_auth_required(self):
        self.assertEqual(EXIT_AUTH_REQUIRED, 2)


class TestIsGatedRepoError(unittest.TestCase):
    """_is_gated_repo_error must detect HuggingFace gated-repo messages."""

    def test_detects_gated_repo_message(self):
        exc = Exception(
            "401 Client Error: Cannot access gated repo for url "
            "https://huggingface.co/ibm-granite/granite-speech-4.1-2b/resolve/..."
        )
        self.assertTrue(_is_gated_repo_error(exc))

    def test_detects_access_to_model_restricted(self):
        exc = Exception(
            "Access to model ibm-granite/granite-speech-4.1-2b is restricted."
        )
        self.assertTrue(_is_gated_repo_error(exc))

    def test_detects_401_restricted(self):
        exc = Exception("401 Client Error. Access is restricted to this repo.")
        self.assertTrue(_is_gated_repo_error(exc))

    def test_ignores_generic_network_error(self):
        exc = Exception("ConnectionError: could not reach huggingface.co")
        self.assertFalse(_is_gated_repo_error(exc))

    def test_ignores_generic_401_without_restricted(self):
        exc = Exception("401 Unauthorized")
        self.assertFalse(_is_gated_repo_error(exc))


class TestDownloadModelExitCodes(unittest.TestCase):
    """download_model must return correct exit codes for each failure mode."""

    def test_unknown_engine_returns_failure(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(download_model("nonexistent", d), EXIT_FAILURE)

    def test_already_downloaded_returns_success(self):
        with tempfile.TemporaryDirectory() as d:
            engine_dir = os.path.join(d, "granite")
            os.makedirs(engine_dir)
            with open(os.path.join(engine_dir, "config.json"), "w") as f:
                f.write("{}")
            self.assertEqual(download_model("granite", d), EXIT_SUCCESS)

    def test_gated_repo_returns_auth_required(self):
        """A gated-repo error from snapshot_download must yield EXIT_AUTH_REQUIRED."""
        mock_hf = MagicMock()
        mock_hf.snapshot_download.side_effect = Exception(
            "401 Client Error. Cannot access gated repo for url ..."
            "Access to model ibm-granite/granite-speech-4.1-2b is restricted."
        )
        with patch.dict("sys.modules", {"huggingface_hub": mock_hf}):
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(download_model("granite", d), EXIT_AUTH_REQUIRED)

    def test_network_error_returns_failure(self):
        """A generic network error must yield EXIT_FAILURE, not EXIT_AUTH_REQUIRED."""
        mock_hf = MagicMock()
        mock_hf.snapshot_download.side_effect = Exception("ConnectionError: timeout")
        with patch.dict("sys.modules", {"huggingface_hub": mock_hf}):
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(download_model("granite", d), EXIT_FAILURE)

    def test_download_does_not_pass_token(self):
        """snapshot_download must be called with token=None when no token is provided."""
        mock_hf = MagicMock()
        mock_hf.snapshot_download.return_value = "/fake/path"
        with patch.dict("sys.modules", {"huggingface_hub": mock_hf}):
            with tempfile.TemporaryDirectory() as d:
                download_model("granite", d)
                call_kwargs = mock_hf.snapshot_download.call_args
                self.assertIn("token", call_kwargs.kwargs,
                    "snapshot_download must receive an explicit 'token' keyword argument")
                self.assertIsNone(call_kwargs.kwargs["token"],
                    "snapshot_download token must be None for anonymous downloads")

    def test_download_passes_token_when_provided(self):
        """snapshot_download must receive the user-provided token string."""
        mock_hf = MagicMock()
        mock_hf.snapshot_download.return_value = "/fake/path"
        with patch.dict("sys.modules", {"huggingface_hub": mock_hf}):
            with tempfile.TemporaryDirectory() as d:
                download_model("granite", d, token="hf_test123")
                call_kwargs = mock_hf.snapshot_download.call_args
                self.assertEqual(call_kwargs.kwargs.get("token"), "hf_test123",
                    "snapshot_download must receive the exact token string passed to download_model")


class TestGraniteSetupLauncher(unittest.TestCase):
    """Installed-model setup launch helpers must pass the expected arguments."""

    def test_launch_raises_when_setup_script_missing(self):
        with patch("speakeasy.model_downloader.find_granite_setup_script", return_value=None):
            with self.assertRaises(FileNotFoundError):
                launch_granite_setup_script()

    def test_launch_passes_target_dir_to_powershell(self):
        script = Path(r"C:\Program Files\SpeakEasy AI Granite\granite-model-setup.ps1")
        target_dir = r"C:\Users\kenpe\AppData\Local\SpeakEasy AI\models"

        with patch("speakeasy.model_downloader.find_granite_setup_script", return_value=script):
            with patch(
                "speakeasy.model_downloader.ctypes.windll.shell32.ShellExecuteW",
                return_value=42,
            ) as shell_execute:
                rc = launch_granite_setup_script(target_dir=target_dir)

        self.assertEqual(rc, 42)
        shell_execute.assert_called_once_with(
            None,
            "open",
            "powershell.exe",
            f'-NoProfile -ExecutionPolicy Bypass -File "{script}" -TargetDir "{target_dir}"',
            str(script.parent),
            1,
        )


