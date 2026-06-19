"""Dictation controller — owns the record → transcribe → paste state machine.

Part of the Phase 6 MainWindow decomposition (plan §9).  This is a plain
``QObject`` controller that holds a back-reference to the owning
:class:`~speakeasy.main_window.MainWindow` and reaches into its widgets, state,
audio recorder, and the :class:`~speakeasy.core.contract.TranscriptionService`;
it owns no UI of its own.  Heavy ML imports stay behind the service boundary —
this module must not import torch/transformers/librosa/accelerate at module
scope.
"""

from __future__ import annotations

import datetime
import logging
from typing import Optional, TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QObject, QTimer, Slot

from ..audio import play_beep
from ..clipboard import set_clipboard_text, simulate_paste
from .._constants import STATE_RESET_ERROR_MS, STATE_RESET_IDLE_MS
from ..core.contract import TranscriptionOptions
from ..workers import Worker

log = logging.getLogger("speakeasy.main_window")

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..main_window import MainWindow


class DictationController(QObject):
    """Drive the recording / transcription / professional-cleanup flow."""

    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__(main_window)
        self._mw = main_window

    def _set_dictation_state(self, state) -> None:
        mw = self._mw
        mw._dictation_state = state
        mw._update_global_status()
        self._refresh_dictation_buttons()

    def _refresh_dictation_buttons(self) -> None:
        """Enable/disable and relabel the record toggle button based on dictation + model state."""
        from ..main_window import DictationState, ModelStatus

        mw = self._mw
        is_idle = mw._dictation_state == DictationState.IDLE
        is_recording = mw._dictation_state == DictationState.RECORDING
        is_processing = mw._dictation_state == DictationState.PROCESSING
        model_ready = mw._model_status in (ModelStatus.READY, ModelStatus.VALIDATED)
        if is_recording:
            mw._btn_record.setEnabled(True)
            self._set_record_button_state("recording")
        elif is_processing:
            mw._btn_record.setEnabled(False)
            self._set_record_button_state("processing")
        else:
            mw._btn_record.setEnabled(is_idle and model_ready)
            self._set_record_button_state("idle" if model_ready else "disabled")

    def _set_record_button_state(self, state: str) -> None:
        from ..theme import Color, primary_record_button_style

        mw = self._mw
        if state == "recording":
            title = "Recording..."
            status = "Recording"
            dot_color = Color.DANGER
        elif state == "processing":
            title = "Transcribing..."
            status = "Please wait"
            dot_color = Color.INFO
        elif state == "disabled":
            title = "Start Recording"
            status = "Please wait"
            dot_color = Color.TEXT_MUTED
        else:
            title = "Start Recording"
            status = "Ready"
            dot_color = Color.SUCCESS

        mw._btn_record.setText("")
        mw._btn_record.setAccessibleName(f"{title}, {status}")
        mw._btn_record.setStyleSheet(primary_record_button_style(state))
        mw._record_title.setText(title)
        mw._record_dot.setStyleSheet(f"color: {dot_color}; background: transparent; font-weight: 700;")
        mw._record_status.setText(status)

    @Slot()
    def _on_toggle_recording(self) -> None:
        """Single hotkey/button handler — start when idle, stop when recording."""
        from ..main_window import DictationState

        mw = self._mw
        if mw._dictation_state == DictationState.IDLE:
            self._on_start_recording()
        elif mw._dictation_state == DictationState.RECORDING:
            self._on_stop_and_transcribe()

    @Slot()
    def _on_start_recording(self) -> None:
        from ..main_window import DictationState, ModelStatus

        mw = self._mw
        if mw._dictation_state != DictationState.IDLE:
            return
        if mw._model_status not in (ModelStatus.READY, ModelStatus.VALIDATED):
            mw._log_ui("Cannot record — model not ready yet", error=True)
            return
        # Health-check the audio stream before recording
        if not mw._recorder.stream_is_alive():
            mw._log_ui("Audio stream stale — attempting recovery…")
            if not mw._recorder.recover_stream():
                mw._log_ui(
                    "Microphone not responding — try changing the audio "
                    "device in Settings",
                    error=True,
                )
                return
            mw._log_ui("Audio stream recovered")
        play_beep((600, 900))   # ascending chirp → "go!"
        mw._recorder.start_recording()
        self._set_dictation_state(DictationState.RECORDING)
        mw._log_ui("Recording started")

    @Slot()
    def _on_stop_and_transcribe(self) -> None:
        """Stop recording, trim, transcribe in-process, clipboard, paste — threaded."""
        from ..main_window import DictationState

        mw = self._mw
        if mw._dictation_state != DictationState.RECORDING:
            return
        play_beep((900, 500))   # descending chirp → "done"
        self._set_dictation_state(DictationState.PROCESSING)

        # Pause NVIDIA Management Library polling while Granite transcribes.
        # On some driver/CUDA combinations, overlapping NVML queries and CUDA
        # generation calls can deadlock the worker and leave the UI stuck.
        mw._res_monitor.stop()

        # Wait for any in-flight metrics poll to finish before dispatching
        # the transcription worker so NVML and CUDA calls do not overlap.
        import time as _time
        _deadline = _time.monotonic() + 2.0
        while mw._res_monitor.is_in_flight and _time.monotonic() < _deadline:
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.processEvents()
            _time.sleep(0.05)

        # Get raw audio (fast, on main thread)
        audio = mw._recorder.get_raw_audio()
        if audio is None:
            mw._log_ui("No audio recorded", error=True)
            mw._res_monitor.start()
            self._set_dictation_state(DictationState.IDLE)
            return

        mw._log_ui(f"Recording stopped \u2014 captured {len(audio)/mw.settings.sample_rate:.1f}s of audio")

        self._suspend_mic_stream_for_processing()

        # Heavy work on thread pool — NO clipboard ops here
        def _process():
            # Trim silence
            trim_result = mw._recorder.trim_silence(audio)
            if trim_result is None:
                raise RuntimeError("No speech detected — audio was pure silence")
            trimmed, pct = trim_result
            if pct > 1:
                log.info("Trimmed %.0f%% silence", pct)

            # Contiguous copy — trim_silence returns a view/slice that can
            # cause native-code crashes in CUDA / torch.
            trimmed = np.ascontiguousarray(trimmed, dtype=np.float32)

            # Resample to 16 kHz at the service boundary (the engine still
            # treats its input as 16 kHz).  Per-request parameters travel with
            # the call via TranscriptionOptions instead of mutating engine state.
            audio_16k = mw._model_controller._resample_to_16k(trimmed, mw.settings.sample_rate)
            options = TranscriptionOptions(
                task=mw.settings.speech_task,
                language=mw.settings.language,
                translation_target=mw.settings.translation_target_language,
                keyword_bias=mw.settings.keyword_bias,
                punctuation=mw.settings.punctuation,
                formatting_style=mw.settings.formatting_style,
                timeout_s=mw.settings.inference_timeout,
            )

            # Transcribe in-process
            return mw._service.transcribe(audio_16k, options).text

        worker = Worker(_process)
        worker.signals.result.connect(self._on_transcription_result)
        worker.signals.error.connect(self._on_transcription_error)
        mw._engine_pool.start(worker)

    @Slot(object)
    def _on_transcription_result(self, text: str) -> None:
        """Handle transcription result — runs on MAIN THREAD (safe for clipboard)."""
        from ..main_window import DictationState

        mw = self._mw
        mw._res_monitor.start()
        self._resume_mic_stream_after_processing()
        text = str(text).strip()
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        if text:
            self._set_dictation_state(DictationState.SUCCESS)
            mw._log_ui(f"Transcribed: {len(text)} chars")

            # AI Writing Profiles: send to OpenAI for cleanup
            if (
                mw.settings.professional_mode
                and mw._text_processor is not None
                and mw._active_preset is not None
            ):
                mw._log_ui("Cleaning up text…")

                preset = mw._active_preset
                processor = mw._text_processor

                def _cleanup():
                    result = processor.process(
                        text,
                        preset=preset,
                    )
                    log.info("Professional cleanup worker finished (%d chars)", len(result))
                    return result

                # Store context for the bound-method handlers so we
                # don't need lambdas (lambdas prevent QObject connection
                # tracking and allow the Worker to be GC'd prematurely).
                mw._pro_context = (ts, text)
                mw._pro_worker = Worker(_cleanup)
                mw._pro_worker.setAutoDelete(False)  # we manage lifetime
                mw._pro_worker.signals.result.connect(self._on_professional_result)
                mw._pro_worker.signals.error.connect(self._on_professional_error)
                mw._pro_worker.signals.finished.connect(self._on_professional_finished)
                mw._update_global_status()
                mw._pool.start(mw._pro_worker)

                # Safety timeout — if signal delivery fails for any
                # reason, fall back after the API timeout + buffer.
                mw._pro_timeout = QTimer(mw)
                mw._pro_timeout.setSingleShot(True)
                mw._pro_timeout.timeout.connect(self._on_professional_timeout)
                mw._pro_timeout.start(20_000)  # 20 s
                return

            self._add_history(ts, text, success=True)

            copied = True
            if mw._chk_auto_copy.isChecked():
                copied = set_clipboard_text(text)  # MAIN THREAD — safe
                if copied:
                    mw._log_ui("Copied to clipboard")
                else:
                    mw._log_ui("Failed to copy to clipboard", error=True)

            if copied and mw._chk_auto_paste.isChecked():
                # Run paste in a thread to avoid blocking UI during modifier wait
                def _paste():
                    simulate_paste(wait_for_modifiers=mw._chk_hotkeys.isChecked())
                w = Worker(_paste)
                mw._pool.start(w)
        else:
            mw._log_ui("Transcription returned empty text")
            self._add_history(ts, "(empty)", success=True)
            self._set_dictation_state(DictationState.SUCCESS)

        QTimer.singleShot(
            STATE_RESET_IDLE_MS,
            lambda: self._set_dictation_state(DictationState.IDLE)
            if mw._dictation_state in (DictationState.SUCCESS, DictationState.ERROR)
            else None,
        )

    @Slot(object)
    def _on_professional_result(self, cleaned_raw: object) -> None:
        """Handle the cleaned text from AI Writing Profiles."""
        from ..main_window import DictationState

        mw = self._mw
        log.info("Professional result signal delivered to main thread")
        ctx = mw._pro_context  # read BEFORE cancel clears it
        self._cancel_pro_timeout()
        if ctx is None:
            return  # already handled (e.g. by timeout)
        ts, original = ctx
        cleaned = str(cleaned_raw).strip()

        # Forward token stats to Developer Panel
        if mw._dev_panel is not None and mw._text_processor is not None:
            tps, ti, to, llm_seq = mw._text_processor.token_stats
            mw._dev_panel.realtime_widget.update_tokens(tps, ti, to, seq=llm_seq)

        if cleaned and cleaned != original:
            mw._log_ui(f"Professional cleanup: {len(original)} -> {len(cleaned)} chars")
            self._add_history(ts, cleaned, success=True, original_text=original)
            output = cleaned
        else:
            mw._log_ui("Professional cleanup returned unchanged text")
            self._add_history(ts, original, success=True)
            output = original

        copied = True
        if mw._chk_auto_copy.isChecked():
            copied = set_clipboard_text(output)
            if copied:
                mw._log_ui("Copied to clipboard")
            else:
                mw._log_ui("Failed to copy to clipboard", error=True)

        if copied and mw._chk_auto_paste.isChecked():
            def _paste():
                simulate_paste(wait_for_modifiers=mw._chk_hotkeys.isChecked())
            w = Worker(_paste)
            mw._pool.start(w)

        QTimer.singleShot(
            STATE_RESET_IDLE_MS,
            lambda: self._set_dictation_state(DictationState.IDLE)
            if mw._dictation_state in (DictationState.SUCCESS, DictationState.ERROR)
            else None,
        )

    @Slot(str)
    def _on_professional_error(self, err: str) -> None:
        """AI Writing Profiles cleanup failed — fall back to raw text."""
        from ..main_window import DictationState

        mw = self._mw
        log.info("Professional error signal delivered to main thread")
        ctx = mw._pro_context  # read BEFORE cancel clears it
        self._cancel_pro_timeout()
        if ctx is None:
            return  # already handled (e.g. by timeout)
        ts, original = ctx
        mw._log_ui(f"Professional cleanup failed: {err}", error=True)
        self._add_history(ts, original, success=True)

        copied = True
        if mw._chk_auto_copy.isChecked():
            copied = set_clipboard_text(original)
            if copied:
                mw._log_ui("Copied original text to clipboard (cleanup failed)")
            else:
                mw._log_ui("Failed to copy to clipboard", error=True)

        if copied and mw._chk_auto_paste.isChecked():
            def _paste():
                simulate_paste(wait_for_modifiers=mw._chk_hotkeys.isChecked())
            w = Worker(_paste)
            mw._pool.start(w)

        QTimer.singleShot(
            STATE_RESET_IDLE_MS,
            lambda: self._set_dictation_state(DictationState.IDLE)
            if mw._dictation_state in (DictationState.SUCCESS, DictationState.ERROR)
            else None,
        )

    @Slot()
    def _on_professional_finished(self) -> None:
        """Worker done — drop the reference (prevent leak)."""
        mw = self._mw
        mw._pro_worker = None
        mw._update_global_status()

    def _cancel_pro_timeout(self) -> None:
        """Stop the safety timer and clear professional-mode context."""
        mw = self._mw
        if mw._pro_timeout is not None:
            mw._pro_timeout.stop()
            mw._pro_timeout.deleteLater()
            mw._pro_timeout = None
        mw._pro_context = None

    @Slot()
    def _on_professional_timeout(self) -> None:
        """Safety net — professional cleanup did not complete in time."""
        from ..main_window import DictationState

        mw = self._mw
        ctx = mw._pro_context
        mw._pro_timeout = None
        mw._pro_context = None
        mw._pro_worker = None
        mw._update_global_status()
        if ctx is None:
            return  # result/error already handled normally
        ts, original = ctx
        log.warning("Professional cleanup timed out — falling back to original text")
        mw._log_ui("Professional cleanup timed out — using original text", error=True)
        self._add_history(ts, original, success=True)

        copied = True
        if mw._chk_auto_copy.isChecked():
            copied = set_clipboard_text(original)
            if copied:
                mw._log_ui("Copied original text to clipboard")
            else:
                mw._log_ui("Failed to copy to clipboard", error=True)

        if copied and mw._chk_auto_paste.isChecked():
            def _paste():
                simulate_paste(wait_for_modifiers=mw._chk_hotkeys.isChecked())
            w = Worker(_paste)
            mw._pool.start(w)

        QTimer.singleShot(
            STATE_RESET_IDLE_MS,
            lambda: self._set_dictation_state(DictationState.IDLE)
            if mw._dictation_state in (DictationState.SUCCESS, DictationState.ERROR)
            else None,
        )

    @Slot(str)
    def _on_transcription_error(self, err: str) -> None:
        from ..main_window import DictationState

        mw = self._mw
        mw._res_monitor.start()
        self._resume_mic_stream_after_processing()
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._set_dictation_state(DictationState.ERROR)

        # Detect CUDA errors and trigger automatic model reload so the next
        # transcription attempt has a clean GPU context.
        is_cuda_error = any(s in err for s in (
            "CUDA error", "AcceleratorError", "cudaError",
        ))
        if is_cuda_error and mw._service.is_loaded:
            mw._log_ui("CUDA error detected — reloading model to recover…", error=True)
            self._add_history(ts, "CUDA error — reloading model…", success=False)
            mw._model_controller._on_reload_model()
            return

        mw._log_ui(f"Transcription error: {err}", error=True)
        self._add_history(ts, f"Error: {err}", success=False)
        QTimer.singleShot(
            STATE_RESET_ERROR_MS,
            lambda: self._set_dictation_state(DictationState.IDLE)
            if mw._dictation_state in (DictationState.SUCCESS, DictationState.ERROR)
            else None,
        )

    def _add_history(
        self,
        timestamp: str,
        text: str,
        success: bool,
        original_text: Optional[str] = None,
    ) -> None:
        from ..history_widget import _HistoryEntry

        mw = self._mw
        if mw._dev_panel is None:
            mw._history_buffer.append((timestamp, text, success, original_text))
            return

        hw = mw._dev_panel.history_widget
        entry = _HistoryEntry(
            timestamp, text, success, parent=hw.history_content,
            original_text=original_text,
        )
        count = hw.history_layout.count()
        hw.history_layout.insertWidget(max(0, count - 1), entry)

    def _suspend_mic_stream_for_processing(self) -> None:
        """Close the live input stream before model inference starts."""
        mw = self._mw
        if mw._mic_suspended_for_processing:
            return
        try:
            mw._recorder.close_stream()
            mw._mic_suspended_for_processing = True
            mw._log_ui("Microphone stream suspended for transcription")
        except Exception as exc:
            mw._log_ui(f"Microphone suspend failed: {exc}", error=True)

    def _resume_mic_stream_after_processing(self) -> None:
        """Re-open the live input stream after model inference finishes."""
        mw = self._mw
        if not mw._mic_suspended_for_processing:
            return
        try:
            mw._recorder.open_stream()
            mw._log_ui("Microphone stream resumed")
        except Exception as exc:
            mw._log_ui(f"Microphone resume failed: {exc}", error=True)
        finally:
            mw._mic_suspended_for_processing = False

        # Delayed health check — verify the stream is actually delivering audio
        def _verify_stream():
            if not mw._recorder.stream_is_alive():
                mw._log_ui("Microphone stream stale after resume — recovering…")
                if mw._recorder.recover_stream():
                    mw._log_ui("Microphone stream recovered after resume")
                else:
                    mw._log_ui(
                        "Microphone recovery failed — try changing the "
                        "audio device in Settings",
                        error=True,
                    )

        QTimer.singleShot(500, _verify_stream)
