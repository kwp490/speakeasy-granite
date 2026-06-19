"""Model controller — owns the model lifecycle and the Granite setup-prompt flow.

Part of the Phase 6 MainWindow decomposition (plan §9).  This is a plain
``QObject`` controller that holds a back-reference to the owning
:class:`~speakeasy.main_window.MainWindow` and reaches into its widgets, state,
and the :class:`~speakeasy.core.contract.TranscriptionService`; it owns no UI of
its own.  Heavy ML imports stay behind the service boundary — this module must
not import torch/transformers/librosa/accelerate at module scope.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtWidgets import QMessageBox

from ..core.model_source import LocalDirSource
from ..engines.registry import create_service
from ..workers import Worker

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..core.contract import TranscriptionService
    from ..main_window import MainWindow


class ModelController(QObject):
    """Drive model load/reload/validate and the Granite setup-prompt dialogs."""

    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__(main_window)
        self._mw = main_window

    def _set_model_status(self, status) -> None:
        from ..theme import Color as TC
        from ..main_window import ModelStatus

        mw = self._mw
        mw._model_status = status
        color_map = {
            ModelStatus.READY: TC.SUCCESS,
            ModelStatus.VALIDATED: TC.SUCCESS,
            ModelStatus.LOADING: TC.WARNING,
            ModelStatus.NOT_LOADED: TC.TEXT_MUTED,
            ModelStatus.VALIDATING: TC.INFO,
            ModelStatus.ERROR: TC.DANGER,
        }
        color = color_map.get(status, TC.TEXT_MUTED)
        mw._lbl_model_status.setText(
            f'Status: <span style="color:{color}"><b>{status.value}</b></span>'
        )
        if mw._dev_panel is not None:
            mw._dev_panel.realtime_widget.update_engine_status(
                mw._service.descriptor().name, mw.settings.device, status.value, color,
            )
        mw._update_global_status()
        mw._dictation_controller._refresh_dictation_buttons()

    def _build_service_from_settings(self) -> "TranscriptionService":
        """Construct the transcription service implied by ``model_source``.

        A ``remote`` source yields a :class:`RemoteEngineClient` (HTTP, no torch);
        anything else yields the in-process service for the configured engine,
        whose heavy imports are deferred to model-load time.
        """
        mw = self._mw
        raw = mw.settings.model_source or {}
        if isinstance(raw, dict) and raw.get("type") == "remote":
            try:
                from ..core.model_source import parse as parse_source
                from ..services.remote_client import RemoteEngineClient

                source = parse_source(raw)
                return RemoteEngineClient(source)
            except Exception:  # noqa: BLE001 - fall back to local on bad config
                logging.getLogger("speakeasy").warning(
                    "Invalid remote model_source; falling back to local engine",
                    exc_info=True,
                )
        return create_service(mw.settings.engine)

    def _load_model(self) -> None:
        """Begin model loading on a worker thread."""
        from ..main_window import ModelStatus

        mw = self._mw
        mw._device_fallback_to_cpu = False
        self._set_model_status(ModelStatus.LOADING)
        mw._model_load_start = time.time()
        mw._loading_timer.start()
        mw._log_ui(f"Loading {mw._service.descriptor().name} model…")

        def _do_load():
            mw._service.load(
                LocalDirSource(path=mw.settings.model_path), mw.settings.device
            )

        worker = Worker(_do_load)
        worker.signals.result.connect(self._on_model_loaded)
        worker.signals.error.connect(self._on_model_load_error)
        mw._engine_pool.start(worker)

    @Slot(object)
    def _on_model_loaded(self, _result) -> None:
        from ..main_window import ModelStatus

        mw = self._mw
        mw._loading_timer.stop()
        elapsed = time.time() - mw._model_load_start
        actual_device = self._actual_engine_device()
        mw._device_fallback_to_cpu = (
            mw.settings.device == "cuda" and actual_device == "cpu"
        )
        self._set_model_status(ModelStatus.READY)
        device_label = "CPU" if actual_device == "cpu" else "GPU"
        mw._lbl_engine.setText(f"Engine: {mw._service.descriptor().name}  \u00b7  Device: {device_label}")
        mw._log_ui(f"Model loaded in {elapsed:.1f}s")

    def _actual_engine_device(self) -> str:
        mw = self._mw
        device = mw._service.health().device or mw.settings.device
        return "cuda" if str(device).lower().startswith("cuda") else "cpu"

    @staticmethod
    def _resample_to_16k(audio: np.ndarray, source_sr: int) -> np.ndarray:
        """Resample recorded audio to 16 kHz before the service boundary.

        Delegates to the single resampling implementation in
        :mod:`speakeasy.core.resample` (soxr primary).  Imported lazily so the
        UI never imports the resampler at module scope.
        """
        from ..core.resample import ensure_16khz

        return ensure_16khz(audio, source_sr)

    @Slot(str)
    def _on_model_load_error(self, err: str) -> None:
        from ..main_window import ModelStatus

        mw = self._mw
        mw._loading_timer.stop()
        self._set_model_status(ModelStatus.ERROR)
        mw._log_ui(f"Model load failed: {err}", error=True)

    def _update_loading_label(self) -> None:
        """Update the status label with elapsed loading time."""
        from ..theme import Color as TC
        from ..main_window import ModelStatus

        mw = self._mw
        if mw._model_status == ModelStatus.LOADING:
            elapsed = int(time.time() - mw._model_load_start)
            mw._lbl_model_status.setText(
                f'Status: <span style="color:{TC.WARNING}"><b>Loading… {elapsed}s</b></span>'
            )

    @Slot()
    def _on_reload_model(self) -> None:
        """Unload then reload the model."""
        from ..main_window import ModelStatus

        mw = self._mw
        mw._log_ui("Reloading model…")

        def _do_reload():
            mw._service.unload()
            mw._service.load(
                LocalDirSource(path=mw.settings.model_path), mw.settings.device
            )

        mw._device_fallback_to_cpu = False
        self._set_model_status(ModelStatus.LOADING)
        mw._model_load_start = time.time()
        mw._loading_timer.start()

        worker = Worker(_do_reload)
        worker.signals.result.connect(self._on_model_loaded)
        worker.signals.error.connect(self._on_model_load_error)
        mw._engine_pool.start(worker)

    # ── Granite setup prompt ──────────────────────────────────────────────────

    def _prompt_model_setup_on_start(self) -> None:
        """Show the Granite setup dialog at startup when model is missing."""
        mw = self._mw
        if self._prompt_granite_setup():
            # User ran setup successfully — try loading
            if self._granite_model_ready():
                self._load_model()
            else:
                mw._log_ui("Model still not found after setup", error=True)
        else:
            mw._log_ui(
                "Model setup declined — use Settings to configure later",
                error=True,
            )

    def _granite_model_ready(self) -> bool:
        """Return True if Granite model files are present locally."""
        from ..model_downloader import model_ready
        return model_ready("granite", self._mw.settings.model_path)

    def _granite_model_health_summary(self) -> str:
        """Return a user-facing summary of Granite model health."""
        from ..model_downloader import model_health
        return model_health("granite", self._mw.settings.model_path).summary()

    def _prompt_granite_setup(self) -> bool:
        """Show a dialog explaining Granite model download requirements.

        If the user chooses to proceed, launch ``granite-model-setup.ps1``
        and return True if the model was successfully downloaded.
        If the user declines, return False.
        """
        mw = self._mw
        msg = QMessageBox(mw)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("IBM Granite Speech — Setup Required")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(
            "The IBM Granite Speech model is missing or incomplete and must be "
            "repaired before local transcription can run."
        )
        msg.setInformativeText(
            "The model is publicly available — no HuggingFace account or "
            "access token is required.<br><br>"
            f"Health check:<br>&nbsp;&nbsp;&nbsp;{self._granite_model_health_summary()}<br><br>"
            "Model page:<br>"
            '&nbsp;&nbsp;&nbsp;<a href="https://huggingface.co/ibm-granite/granite-speech-4.1-2b">'
            "https://huggingface.co/ibm-granite/granite-speech-4.1-2b</a><br><br>"
            "Would you like to download or repair the Granite model now?"
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.Yes)

        if msg.exec() != QMessageBox.StandardButton.Yes:
            return False

        # In source (non-frozen) mode, download directly — no elevation needed
        # since dev-temp/ is user-writable and speakeasy.exe doesn't exist.
        if not getattr(sys, "frozen", False):
            return self._run_source_model_download()

        # Launch granite-model-setup.ps1 (frozen/installed builds)
        return self._run_granite_setup_script()

    def _run_source_model_download(self) -> bool:
        """Download the public Granite model directly (no token required)."""
        mw = self._mw
        mw._log_ui("Downloading Granite model (this may take several minutes)...")
        from ..model_download_dialog import run_model_download_dialog

        if run_model_download_dialog(mw.settings.model_path, mw):
            mw._log_ui("Granite model downloaded successfully")
            return True
        QMessageBox.warning(
            mw,
            "Download Failed",
            "The model download failed. Check the log for details.\n\n"
            "You can retry from Settings or run:\n"
            "  uv run python -m speakeasy download-model",
        )
        return False

    def _run_granite_setup_script(self) -> bool:
        """Launch ``granite-model-setup.ps1`` and return True if the model
        is present afterwards."""
        mw = self._mw
        from ..model_downloader import (
            get_granite_setup_script_candidates,
            launch_granite_setup_script,
        )

        install_script, repo_script = get_granite_setup_script_candidates()
        if install_script == repo_script:
            searched_paths = f"  {install_script}"
        else:
            searched_paths = f"  {install_script}\n  {repo_script}"

        model_dir = Path(mw.settings.model_path) / "granite"

        mw._log_ui("Launching Granite model setup…")
        try:
            ret = launch_granite_setup_script(target_dir=mw.settings.model_path)
        except FileNotFoundError:
            QMessageBox.critical(
                mw,
                "Setup Script Missing",
                f"Could not find granite-model-setup.ps1 in:\n"
                f"{searched_paths}\n\n"
                "Please reinstall SpeakEasy AI Granite or run the Granite setup manually.",
            )
            return False
        except Exception as exc:
            mw._log_ui(f"Failed to launch Granite setup: {exc}", error=True)
            return False

        if ret <= 32:
            mw._log_ui("Granite setup was cancelled or failed to launch", error=True)
            return False

        confirm = QMessageBox.question(
            mw,
            "Granite Setup",
            "The Granite model setup wizard has been launched in a\n"
            "separate window. Click OK once it has finished.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )
        if confirm == QMessageBox.StandardButton.Cancel:
            return False

        # Check if the model was actually downloaded
        if self._granite_model_ready():
            mw._log_ui("Granite model is ready")
            return True
        else:
            health_summary = self._granite_model_health_summary()
            QMessageBox.warning(
                mw,
                "Granite Model Not Ready",
                "The Granite model still looks incomplete after setup.\n\n"
                f"Expected model directory:\n  {model_dir}\n\n"
                f"Health check:\n  {health_summary}\n\n"
                "You can try again later from Settings, or run\n"
                "granite-model-setup.ps1 from the install directory.",
            )
            return False
