"""End-to-end regressions for the Phase 6 UI simplification (plan §12.2).

These pytest-qt tests construct a *real* ``MainWindow`` in offscreen mode and
drive the record → transcribe → paste loop with a deterministic ``FakeEngine``
behind the ``TranscriptionService`` boundary.  They prove that the behaviour
that survived the controller extraction (record-button state machine, hotkey
wiring, auto-copy/auto-paste path) still works against the live widgets — the
executable counterpart to the AST pins in ``test_main_window_layout.py`` and
``test_integration_full_flow.py``.

The clipboard and the paste keystroke are mocked (no OS side effects); the audio
recorder is the headless fake from ``conftest.py``; transcription is the
in-process ``FakeEngine`` so the whole flow is hermetic and deterministic.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _qt_available() -> bool:
    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _qt_available(), reason="PySide6 not available")


class _SyncPool:
    """A QThreadPool-like facade that runs runnables inline on the caller.

    Running ``Worker`` instances synchronously on the main (test) thread makes
    their ``result``/``error`` signals fire via a direct connection, so the full
    record→transcribe→paste flow completes within the driving call with no event
    loop waiting and no thread races.
    """

    def setMaxThreadCount(self, count: int) -> None:  # noqa: N802 - Qt API shape
        pass

    def setExpiryTimeout(self, ms: int) -> None:  # noqa: N802 - Qt API shape
        pass

    def start(self, worker) -> None:
        worker.run()

    def waitForDone(self, *args, **kwargs) -> bool:  # noqa: N802 - Qt API shape
        return True

    def shutdown(self, *args, **kwargs) -> None:
        pass

    def stop(self) -> None:
        pass


@pytest.fixture
def live_main_window(temp_settings_dir, monkeypatch, qtbot):
    """Construct a real MainWindow wired to a deterministic FakeEngine.

    Returns ``(window, mocks)`` where ``mocks`` exposes the patched
    ``set_clipboard_text`` / ``simulate_paste`` / ``play_beep`` so tests can
    assert on the side effects without touching the OS.
    """
    from speakeasy.config import Settings
    from speakeasy.engines.fake import FakeEngine
    from speakeasy.main_window import MainWindow, ModelStatus

    # No real beeps, clipboard writes, or paste keystrokes.
    clipboard = MagicMock(return_value=True)
    paste = MagicMock()
    beep = MagicMock()
    monkeypatch.setattr("speakeasy.ui.dictation_controller.set_clipboard_text", clipboard)
    monkeypatch.setattr("speakeasy.ui.dictation_controller.simulate_paste", paste)
    monkeypatch.setattr("speakeasy.ui.dictation_controller.play_beep", beep)

    settings = Settings()
    settings.hotkeys_enabled = False       # do not register Win32 hotkeys in tests
    settings.professional_mode = False     # straight dictation path
    settings.store_api_key = False

    engine = FakeEngine(transcript="hello world")
    engine.load("/dummy", "cpu")

    mw = MainWindow(settings, engine=engine, engine_pool=_SyncPool())
    qtbot.addWidget(mw)

    # Stop background metrics polling and run all worker dispatch inline so the
    # flow is deterministic.
    mw._res_monitor.stop()
    mw._pool = _SyncPool()

    # The on-disk granite model is absent in CI, so __init__ leaves the status in
    # ERROR; the injected FakeEngine service is ready, so present the model as
    # READY for the dictation path.
    mw._model_controller._set_model_status(ModelStatus.READY)

    mocks = MagicMock()
    mocks.clipboard = clipboard
    mocks.paste = paste
    mocks.beep = beep
    return mw, mocks


def _is_state(mw, name: str) -> bool:
    return mw._dictation_state.name == name


class TestRecordButtonStateMachine:
    def test_toggle_from_idle_starts_recording(self, live_main_window):
        mw, _ = live_main_window
        assert _is_state(mw, "IDLE")

        mw._dictation_controller._on_toggle_recording()

        assert _is_state(mw, "RECORDING")
        assert mw._recorder._recording is True
        assert "Recording" in mw._record_title.text()

    def test_record_blocked_when_model_not_ready(self, live_main_window):
        mw, _ = live_main_window
        from speakeasy.main_window import ModelStatus

        mw._model_controller._set_model_status(ModelStatus.NOT_LOADED)
        mw._dictation_controller._on_start_recording()

        assert _is_state(mw, "IDLE")
        assert mw._recorder._recording is False


class TestEndToEndDictation:
    def test_full_flow_copies_and_pastes(self, live_main_window):
        mw, mocks = live_main_window
        mw._chk_auto_copy.setChecked(True)
        mw._chk_auto_paste.setChecked(True)
        mw._chk_hotkeys.setChecked(False)

        # IDLE -> RECORDING -> (stop) transcribe -> copy -> paste, all inline.
        mw._dictation_controller._on_toggle_recording()
        assert _is_state(mw, "RECORDING")
        mw._dictation_controller._on_toggle_recording()

        mocks.clipboard.assert_called_once_with("hello world")
        mocks.paste.assert_called_once()

    def test_auto_paste_disabled_copies_without_pasting(self, live_main_window):
        mw, mocks = live_main_window
        mw._chk_auto_copy.setChecked(True)
        mw._chk_auto_paste.setChecked(False)

        mw._dictation_controller._on_toggle_recording()
        mw._dictation_controller._on_stop_and_transcribe()

        mocks.clipboard.assert_called_once_with("hello world")
        mocks.paste.assert_not_called()

    def test_auto_copy_disabled_skips_clipboard(self, live_main_window):
        mw, mocks = live_main_window
        mw._chk_auto_copy.setChecked(False)
        mw._chk_auto_paste.setChecked(False)

        mw._dictation_controller._on_toggle_recording()
        mw._dictation_controller._on_stop_and_transcribe()

        mocks.clipboard.assert_not_called()
        mocks.paste.assert_not_called()


class TestHotkeyWiring:
    def test_hotkey_toggle_drives_the_dictation_loop(self, live_main_window):
        mw, mocks = live_main_window
        mw._chk_auto_copy.setChecked(True)
        mw._chk_auto_paste.setChecked(True)

        # The global-hotkey manager's toggle signal must reach the dictation
        # controller after the Phase 6 controller extraction.
        mw._hotkey_mgr.toggle_requested.emit()
        assert _is_state(mw, "RECORDING")

        mw._hotkey_mgr.toggle_requested.emit()
        mocks.clipboard.assert_called_once_with("hello world")
