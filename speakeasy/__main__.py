"""
SpeakEasy AI — entry point.

Usage:
    python -m speakeasy                                          # launch GUI
    python -m speakeasy download-model --token hf_...            # download model
    python -m speakeasy --version                                # print version

Handles single-instance guard, logging setup, and Qt application lifecycle.
"""

from __future__ import annotations

import argparse
import ctypes
import faulthandler
import io
import logging
import logging.handlers
import multiprocessing
import os
import sys


# ── Stdout/stderr safety (needed for PyInstaller --noconsole builds) ─────────
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()


# ── Single-instance mutex (Windows) ──────────────────────────────────────────

_MUTEX_NAME = "Global\\SpeakEasyAIGraniteMutex"
_mutex_handle = None


def release_single_instance_mutex() -> None:
    """Release the single-instance mutex so a restarted process can acquire it."""
    global _mutex_handle
    if _mutex_handle is not None:
        try:
            ctypes.windll.kernel32.CloseHandle(_mutex_handle)  # type: ignore[attr-defined]
        except Exception:
            pass
        _mutex_handle = None


def _ensure_single_instance() -> bool:
    """Return True if this is the only running instance."""
    global _mutex_handle
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        _mutex_handle = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(_mutex_handle)
            _mutex_handle = None
            return False
        return True
    except Exception:
        # Non-Windows or ctypes not available — skip guard
        return True


# ── Logging ──────────────────────────────────────────────────────────────────

def _setup_logging() -> None:
    from speakeasy.config import DEFAULT_LOG_DIR

    log_dir = str(DEFAULT_LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "speakeasy.log")

    # Use a UTF-8 stream for the console handler so Unicode characters
    # don't crash on Windows cp1252 consoles.
    # In PyInstaller --noconsole builds sys.stdout has no real fd.
    try:
        _console_stream = open(
            sys.stdout.fileno(), mode="w", encoding="utf-8",
            errors="replace", closefd=False,
        )
    except (io.UnsupportedOperation, OSError):
        _console_stream = None

    handlers: list[logging.Handler] = []
    try:
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_path, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
            )
        )
    except OSError:
        # Log directory not writable (e.g. restrictive permissions after install).
        # Fall back to console-only logging so the app still starts.
        log_path = "<unavailable>"
    if _console_stream is not None:
        handlers.append(logging.StreamHandler(_console_stream))
    if not handlers:
        handlers.append(logging.NullHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    logging.getLogger("speakeasy").info("=== SpeakEasy AI starting (log: %s) ===", log_path)


# ── CLI ──────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="speakeasy",
        description="SpeakEasy AI Granite — Native Windows Voice-to-Text",
    )
    parser.add_argument(
        "--version", action="store_true", help="Print version and exit"
    )

    sub = parser.add_subparsers(dest="command")

    dl = sub.add_parser("download-model", help="Download IBM Granite Speech model")
    dl.add_argument(
        "--target-dir",
        default=None,
        help="Directory to store models (default: C:\\Program Files\\SpeakEasy AI\\models)",
    )
    dl.add_argument(
        "--token",
        default=None,
        help="HuggingFace access token (not required for Granite — public model)",
    )

    return parser


def _cmd_download_model(args: argparse.Namespace) -> int:
    """Handle the download-model subcommand."""
    from speakeasy.config import DEFAULT_MODELS_DIR
    from speakeasy.model_downloader import download_model

    target_dir = args.target_dir or DEFAULT_MODELS_DIR
    os.makedirs(target_dir, exist_ok=True)

    return download_model("granite", target_dir, token=args.token)


def _ensure_startup_model_ready(settings) -> bool:
    """Ensure the Granite model is available before opening the main window."""
    from PySide6.QtWidgets import QMessageBox
    from speakeasy.model_downloader import (
        get_granite_setup_script_candidates,
        launch_granite_setup_script,
        model_ready,
    )

    if model_ready("granite", settings.model_path):
        return True

    log = logging.getLogger("speakeasy")
    if not getattr(sys, "frozen", False):
        log.warning(
            "Granite model not found at %s; the app will prompt for setup",
            settings.model_path,
        )
        return True

    model_dir = os.path.join(settings.model_path, "granite")
    log.error("Granite model not found at %s (frozen build)", settings.model_path)

    try:
        launch_result = launch_granite_setup_script(target_dir=settings.model_path)
    except FileNotFoundError:
        install_script, repo_script = get_granite_setup_script_candidates()
        QMessageBox.critical(
            None,
            "SpeakEasy AI Granite — Setup Script Missing",
            "Could not find granite-model-setup.ps1 in:\n"
            f"  {install_script}\n"
            f"  {repo_script}\n\n"
            "Please reinstall SpeakEasy AI Granite or run the Granite setup manually.",
        )
        return False
    except Exception as exc:
        log.exception("Failed to launch Granite model setup")
        QMessageBox.critical(
            None,
            "SpeakEasy AI Granite — Setup Launch Failed",
            "The Granite model setup could not be launched.\n\n"
            f"{exc}",
        )
        return False

    if launch_result <= 32:
        log.error("Granite setup launch returned ShellExecute code %s", launch_result)
        QMessageBox.warning(
            None,
            "SpeakEasy AI Granite — Model Setup",
            "The Granite model setup was cancelled or could not be started.\n\n"
            "Run SpeakEasy AI Granite again and accept the elevation prompt, or use the "
            "Start Menu setup entry to install the model.",
        )
        return False

    confirm = QMessageBox.question(
        None,
        "Granite Setup",
        "The Granite model setup wizard has been launched in a\n"
        "separate window. Click OK once it has finished.",
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Ok,
    )
    if confirm == QMessageBox.StandardButton.Cancel:
        return False

    if model_ready("granite", settings.model_path):
        log.info("Granite model detected after startup setup")
        return True

    QMessageBox.warning(
        None,
        "SpeakEasy AI Granite — Model Missing",
        "The Granite model was not detected after setup.\n\n"
        f"Expected model directory:\n  {model_dir}\n\n"
        "You can rerun the setup from the Start Menu or the install directory.",
    )
    return False


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.version:
        from speakeasy import __version__
        print(f"SpeakEasy AI {__version__}")
        return 0

    if args.command == "download-model":
        _setup_logging()
        return _cmd_download_model(args)

    # Default: launch GUI
    try:
        faulthandler.enable()
    except io.UnsupportedOperation:
        pass  # stderr has no fileno() in PyInstaller --noconsole builds

    if not _ensure_single_instance():
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            _app = QApplication(sys.argv)
            QMessageBox.warning(None, "SpeakEasy AI", "Another instance is already running.")
        except Exception:
            print("ERROR: Another instance of SpeakEasy AI is already running.")
        return 1

    _setup_logging()

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from speakeasy.config import Settings
    from speakeasy.theme import app_stylesheet
    from speakeasy.workers import DedicatedWorkerPool

    app = QApplication(sys.argv)
    app.setApplicationName("SpeakEasy AI")
    app.setOrganizationName("SpeakEasy AI")
    app.setStyleSheet(app_stylesheet())

    # Set application icon (taskbar + window title bar)
    _icon_path = os.path.join(
        getattr(sys, '_MEIPASS', os.path.dirname(__file__)),
        'assets', 'app.ico',
    )
    if os.path.isfile(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))

    settings = Settings.load()

    if not _ensure_startup_model_ready(settings):
        return 1

    # Pre-create the engine worker thread BEFORE torch / CUDA DLLs are loaded.
    #
    # On Windows, CUDA registers DllMain(DLL_THREAD_ATTACH) callbacks that
    # fire for every thread created *after* those DLLs load.  A known bug in
    # certain CUDA builds corrupts the stack of any newly created thread via
    # this callback, causing access violations in otherwise-innocent code (even
    # os.path.isdir).  Creating and warming up the engine pool thread here —
    # before the MainWindow import below pulls in torch/CUDA — ensures the
    # thread already exists when the DLLs load and is therefore immune.
    _engine_pool = DedicatedWorkerPool()
    _engine_pool.warmup()

    # Import MainWindow now; this transitively imports granite_transcribe
    # which imports torch and transformers at module level, loading CUDA DLLs.
    # The engine thread is already alive at this point, so its stack is safe.
    from speakeasy.main_window import MainWindow

    window = MainWindow(settings, engine_pool=_engine_pool)
    window.show()

    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
