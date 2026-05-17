"""Tests for the model downloader module."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from speakeasy.model_downloader import (
    GRANITE_REPO_ID,
    GRANITE_REQUIRED_FILES,
    EXIT_AUTH_REQUIRED,
    EXIT_FAILURE,
    EXIT_SUCCESS,
    MODEL_DOWNLOAD_MIN_FREE_BYTES,
    PROGRESS_PREFIX,
    _ENGINE_REPO_MAP,
    _is_gated_repo_error,
    DownloadProgress,
    download_model,
    launch_granite_setup_script,
    model_health,
    model_ready,
)


def _write_complete_granite_model(model_root: str | Path) -> Path:
    engine_dir = Path(model_root) / "granite"
    engine_dir.mkdir(parents=True, exist_ok=True)
    for filename in GRANITE_REQUIRED_FILES:
        path = engine_dir / filename
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
        (engine_dir / shard_name).write_bytes(b"weights")
    return engine_dir


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

    def test_not_ready_when_only_config_exists(self):
        with tempfile.TemporaryDirectory() as d:
            engine_dir = os.path.join(d, "granite")
            os.makedirs(engine_dir)
            with open(os.path.join(engine_dir, "config.json"), "w") as f:
                f.write("{}")
            self.assertFalse(model_ready("granite", d))

    def test_reports_missing_tokenizer_files(self):
        with tempfile.TemporaryDirectory() as d:
            engine_dir = Path(d) / "granite"
            engine_dir.mkdir()
            (engine_dir / "config.json").write_text("{}", encoding="utf-8")
            health = model_health("granite", d)
            self.assertFalse(health.ready)
            self.assertIn("tokenizer.json", health.missing_files)
            self.assertIn("tokenizer_config.json", health.missing_files)
            self.assertIn("vocab.json", health.missing_files)

    def test_not_ready_when_no_dir(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(model_ready("granite", d))

    def test_not_ready_when_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "granite"))
            self.assertFalse(model_ready("granite", d))

    def test_ready_for_granite(self):
        with tempfile.TemporaryDirectory() as d:
            _write_complete_granite_model(d)
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
            _write_complete_granite_model(d)
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


class TestDownloadProgress(unittest.TestCase):
    """download_model should expose structured progress for callers."""

    def test_jsonl_progress_for_already_present_model(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            _write_complete_granite_model(temporary_dir)

            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                result = download_model(
                    "granite",
                    temporary_dir,
                    progress_format="jsonl",
                )

        self.assertEqual(result, EXIT_SUCCESS)
        progress_lines = [
            line for line in stdout.getvalue().splitlines()
            if line.startswith(PROGRESS_PREFIX)
        ]
        payloads = [
            json.loads(line[len(PROGRESS_PREFIX):]) for line in progress_lines
        ]
        self.assertEqual(payloads[0]["phase"], "checking")
        self.assertEqual(payloads[-1]["phase"], "already_present")
        self.assertEqual(payloads[-1]["percent"], 100)

    def test_callback_receives_download_lifecycle_events(self):
        mock_hf = MagicMock()

        def fake_snapshot_download(**kwargs):
            target_dir = Path(kwargs["local_dir"])
            _write_complete_granite_model(target_dir.parent)
            return str(target_dir)

        mock_hf.snapshot_download.side_effect = fake_snapshot_download
        events: list[DownloadProgress] = []
        with patch.dict("sys.modules", {"huggingface_hub": mock_hf}):
            with tempfile.TemporaryDirectory() as temporary_dir:
                result = download_model(
                    "granite",
                    temporary_dir,
                    progress_callback=events.append,
                    progress_format="none",
                )

        self.assertEqual(result, EXIT_SUCCESS)
        self.assertEqual(
            [event.phase for event in events],
            ["checking", "preflight", "downloading", "verifying", "complete"],
        )
        self.assertEqual(events[-1].percent, 100)

    def test_partial_model_is_repaired_instead_of_skipped(self):
        mock_hf = MagicMock()

        def fake_snapshot_download(**kwargs):
            target_dir = Path(kwargs["local_dir"])
            _write_complete_granite_model(target_dir.parent)
            return str(target_dir)

        mock_hf.snapshot_download.side_effect = fake_snapshot_download
        events: list[DownloadProgress] = []
        with patch.dict("sys.modules", {"huggingface_hub": mock_hf}):
            with tempfile.TemporaryDirectory() as temporary_dir:
                engine_dir = Path(temporary_dir) / "granite"
                engine_dir.mkdir()
                (engine_dir / "config.json").write_text("{}", encoding="utf-8")

                result = download_model(
                    "granite",
                    temporary_dir,
                    progress_callback=events.append,
                    progress_format="none",
                )

        self.assertEqual(result, EXIT_SUCCESS)
        self.assertEqual(mock_hf.snapshot_download.call_count, 1)
        self.assertIn("repairing", [event.phase for event in events])

    def test_insufficient_disk_space_returns_failure_before_download(self):
        mock_hf = MagicMock()
        events: list[DownloadProgress] = []
        with patch.dict("sys.modules", {"huggingface_hub": mock_hf}):
            with patch(
                "speakeasy.model_downloader._check_disk_space",
                return_value=(False, 1024, MODEL_DOWNLOAD_MIN_FREE_BYTES),
            ):
                with tempfile.TemporaryDirectory() as temporary_dir:
                    result = download_model(
                        "granite",
                        temporary_dir,
                        progress_callback=events.append,
                        progress_format="none",
                    )

        self.assertEqual(result, EXIT_FAILURE)
        mock_hf.snapshot_download.assert_not_called()
        self.assertEqual(events[-1].phase, "error")
        self.assertIn("Not enough free disk space", events[-1].message)

    def test_progress_format_none_suppresses_stdout(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            _write_complete_granite_model(temporary_dir)

            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                result = download_model(
                    "granite",
                    temporary_dir,
                    progress_format="none",
                )

        self.assertEqual(result, EXIT_SUCCESS)
        self.assertEqual(stdout.getvalue(), "")

    def test_progress_file_receives_jsonl_when_stdout_suppressed(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            _write_complete_granite_model(temporary_dir)
            progress_file = Path(temporary_dir) / "progress.jsonl"

            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                result = download_model(
                    "granite",
                    temporary_dir,
                    progress_format="none",
                    progress_file=progress_file,
                )
            progress_lines = progress_file.read_text(encoding="utf-8").splitlines()

        self.assertEqual(result, EXIT_SUCCESS)
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(all(line.startswith(PROGRESS_PREFIX) for line in progress_lines))
        payloads = [json.loads(line[len(PROGRESS_PREFIX):]) for line in progress_lines]
        self.assertEqual(payloads[-1]["phase"], "already_present")

    def test_check_only_validates_dependencies_without_download(self):
        mock_hf = MagicMock()
        events: list[DownloadProgress] = []
        with patch.dict("sys.modules", {"huggingface_hub": mock_hf}):
            with tempfile.TemporaryDirectory() as temporary_dir:
                progress_file = Path(temporary_dir) / "progress.jsonl"
                result = download_model(
                    "granite",
                    temporary_dir,
                    progress_callback=events.append,
                    progress_format="none",
                    progress_file=progress_file,
                    check_only=True,
                )
                progress_text = progress_file.read_text(encoding="utf-8")

        self.assertEqual(result, EXIT_SUCCESS)
        mock_hf.snapshot_download.assert_not_called()
        self.assertEqual(events[-1].phase, "complete")
        self.assertIn("preflight passed", events[-1].message)
        self.assertIn(PROGRESS_PREFIX, progress_text)

    def test_check_only_reports_dependency_failure(self):
        events: list[DownloadProgress] = []
        with patch.dict("sys.modules", {"huggingface_hub": None}):
            with tempfile.TemporaryDirectory() as temporary_dir:
                result = download_model(
                    "granite",
                    temporary_dir,
                    progress_callback=events.append,
                    progress_format="none",
                    check_only=True,
                )

        self.assertEqual(result, EXIT_FAILURE)
        self.assertEqual(events[-1].phase, "error")
        self.assertIn("Download preflight failed", events[-1].message)

    def test_transient_download_errors_are_retried(self):
        mock_hf = MagicMock()
        attempts = {"count": 0}

        def flaky_snapshot_download(**kwargs):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise Exception("ConnectionError: timeout")
            target_dir = Path(kwargs["local_dir"])
            _write_complete_granite_model(target_dir.parent)
            return str(target_dir)

        mock_hf.snapshot_download.side_effect = flaky_snapshot_download
        events: list[DownloadProgress] = []
        with patch.dict("sys.modules", {"huggingface_hub": mock_hf}):
            with patch("speakeasy.model_downloader.time.sleep") as sleep:
                with tempfile.TemporaryDirectory() as temporary_dir:
                    result = download_model(
                        "granite",
                        temporary_dir,
                        progress_callback=events.append,
                        progress_format="none",
                    )

        self.assertEqual(result, EXIT_SUCCESS)
        self.assertEqual(mock_hf.snapshot_download.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertIn("retrying", [event.phase for event in events])

    def test_invalid_progress_format_raises(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            with self.assertRaises(ValueError):
                download_model(
                    "granite",
                    temporary_dir,
                    progress_format="xml",  # type: ignore[arg-type]
                )


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


