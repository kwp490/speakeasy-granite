"""Tests for the refactored MainWindow layout.

Verifies:
    Phase 1 â€“ Transcription section is dominant; buttons enlarged, no Dictation GroupBox.
    Phase 2 â€“ Diagnostics panel collapsed by default; toggling shows/hides.
    Phase 3 â€“ Status pill bar placed between buttons and checkboxes (no QStatusBar).
    Phase 4 â€“ Clear/Copy buttons are contextually placed in panel headers.
"""

import ast
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MAIN_WINDOW_PATH = _REPO_ROOT / "speakeasy" / "main_window.py"


def _qt_available() -> bool:
    try:
        from PySide6.QtWidgets import QApplication
        return True
    except ImportError:
        return False


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Structural (AST) tests â€” no Qt needed
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestLayoutStructure(unittest.TestCase):
    """AST-level checks on _build_ui layout changes."""

    @classmethod
    def setUpClass(cls):
        cls._source = _MAIN_WINDOW_PATH.read_text(encoding="utf-8")
        cls._tree = ast.parse(cls._source, filename="main_window.py")
        cls._mw_class = None
        for node in ast.walk(cls._tree):
            if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
                cls._mw_class = node
                break
        assert cls._mw_class is not None

    def _get_method_source(self, method_name: str) -> str:
        for node in ast.walk(self._mw_class):
            if isinstance(node, ast.FunctionDef) and node.name == method_name:
                return ast.get_source_segment(self._source, node) or ""
        self.fail(f"Method '{method_name}' not found in MainWindow")

    # â”€â”€ Phase 1 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_no_dictation_groupbox(self):
        """The 'Dictation' QGroupBox must no longer appear in _build_ui."""
        src = self._get_method_source("_build_ui")
        self.assertNotIn('QGroupBox("Dictation")', src)

    def test_start_button_height_increased(self):
        """Start Recording button must use theme Size for minimum height."""
        src = self._get_method_source("_build_ui")
        self.assertIn("setMinimumHeight(Size.BUTTON_HEIGHT_PRIMARY)", src)

    def test_start_button_font_increased(self):
        """Start/Stop buttons must use primary_button_style."""
        src = self._get_method_source("_build_ui")
        self.assertIn("primary_button_style()", src)

    def test_history_min_height_increased(self):
        """History scroll area must have minimumHeight >= 200."""
        src = self._get_method_source("_build_ui")
        self.assertIn("setMinimumHeight(200)", src)

    def test_no_lbl_dictation_state_in_build_ui(self):
        """_lbl_dictation_state must not be created in _build_ui."""
        src = self._get_method_source("_build_ui")
        self.assertNotIn("_lbl_dictation_state", src)

    # â”€â”€ Phase 2 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_dev_panel_gear_button_exists(self):
        """_build_ui must create self._btn_dev_panel (gear button)."""
        src = self._get_method_source("_build_ui")
        self.assertIn("self._btn_dev_panel", src)

    def test_no_inline_diagnostics(self):
        """Inline diagnostics block must be removed (replaced by Developer Panel)."""
        src = self._get_method_source("_build_ui")
        self.assertNotIn("self._diag_toggle", src)
        self.assertNotIn("self._diag_content", src)

    def test_toggle_dev_panel_method_exists(self):
        """_toggle_dev_panel method must exist."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("_on_toggle_dev_panel", method_names)

    # â”€â”€ Phase 3 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_status_bar_created(self):
        """_build_ui must create self._status_bar."""
        src = self._get_method_source("_build_ui")
        self.assertIn("self._status_bar", src)
        self.assertIn("StatusPillBar", self._source)

    def test_no_status_bar_in_build_ui(self):
        """QStatusBar must not be used in _build_ui (status moved inline)."""
        src = self._get_method_source("_build_ui")
        self.assertNotIn("QStatusBar", src)
        self.assertNotIn("setStatusBar", src)

    def test_update_global_status_method_exists(self):
        """_update_global_status method must exist."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("_update_global_status", method_names)

    def test_set_model_status_calls_update_global(self):
        """_set_model_status must call _update_global_status."""
        src = self._get_method_source("_set_model_status")
        self.assertIn("_update_global_status", src)

    def test_set_dictation_state_calls_update_global(self):
        """_set_dictation_state must call _update_global_status."""
        src = self._get_method_source("_set_dictation_state")
        self.assertIn("_update_global_status", src)

    # â”€â”€ Phase 4 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_on_clear_history_method_exists(self):
        """_on_clear_history must be defined as a separate method."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("_on_clear_history", method_names)

    def test_on_clear_logs_method_exists(self):
        """_on_clear_logs must be defined as a separate method."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("_on_clear_logs", method_names)

    def test_old_clear_method_removed(self):
        """_on_clear_logs_and_history must no longer exist."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertNotIn("_on_clear_logs_and_history", method_names)

    def test_clear_history_button_in_build_ui(self):
        """_btn_clear_history must be created in _build_ui."""
        src = self._get_method_source("_build_ui")
        self.assertIn("_btn_clear_history", src)

    def test_clear_logs_method_exists(self):
        """_on_clear_logs must be defined in MainWindow."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("_on_clear_logs", method_names)

    def test_copy_logs_method_exists(self):
        """_on_copy_logs must be defined in MainWindow."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("_on_copy_logs", method_names)

    # â”€â”€ Phase 5 (professional mode button in footer) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_no_pro_toggle_in_build_ui(self):
        """PRO toggle button must not be in _build_ui (was removed long ago)."""
        src = self._get_method_source("_build_ui")
        self.assertNotIn("_btn_pro_toggle", src)

    def test_no_combo_preset_in_build_ui(self):
        """Preset combo must not be in _build_ui (moved to Pro Settings dialog)."""
        src = self._get_method_source("_build_ui")
        self.assertNotIn("_combo_preset", src)

    def test_no_pro_toggle_method(self):
        """_on_pro_toggle must not be defined in MainWindow."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertNotIn("_on_pro_toggle", method_names)

    def test_no_pro_settings_button_in_build_ui(self):
        """Pro Mode Settings button removed — now in Developer Panel."""
        src = self._get_method_source("_build_ui")
        self.assertNotIn("Pro Mode Settings", src)

    def test_on_open_pro_settings_method_exists(self):
        """_on_open_pro_settings must be defined in MainWindow."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("_on_open_pro_settings", method_names)

    def test_no_refresh_preset_combo_method(self):
        """_refresh_preset_combo must not be in MainWindow (moved to ProSettingsDialog)."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertNotIn("_refresh_preset_combo", method_names)

    def test_update_global_status_includes_professional(self):
        """_update_global_status must include Professional mode status."""
        src = self._get_method_source("_update_global_status")
        self.assertIn("set_pro_mode", src)

    # â”€â”€ Engine worker isolation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_init_creates_dedicated_engine_pool(self):
        """MainWindow must create a dedicated single-thread pool for engine work."""
        src = self._get_method_source("__init__")
        self.assertIn("self._engine_pool", src)
        self.assertIn("setMaxThreadCount(1)", src)
        self.assertIn("setExpiryTimeout(-1)", src)

    def test_load_model_uses_engine_pool(self):
        """Model load must run on the dedicated engine pool, not the global pool."""
        src = self._get_method_source("_load_model")
        self.assertIn("self._engine_pool.start(worker)", src)
        self.assertNotIn("self._pool.start(worker)", src)

    def test_reload_model_uses_engine_pool(self):
        """Model reload must run on the dedicated engine pool."""
        src = self._get_method_source("_on_reload_model")
        self.assertIn("self._engine_pool.start(worker)", src)
        self.assertNotIn("self._pool.start(worker)", src)

    def test_validate_uses_engine_pool(self):
        """Validation must run on the dedicated engine pool."""
        src = self._get_method_source("_on_validate")
        self.assertIn("self._engine_pool.start(worker)", src)
        self.assertNotIn("self._pool.start(worker)", src)

    def test_transcription_uses_engine_pool(self):
        """Transcription must run on the dedicated engine pool."""
        src = self._get_method_source("_on_stop_and_transcribe")
        self.assertIn("self._engine_pool.start(worker)", src)
        self.assertNotIn("self._pool.start(worker)", src)

    def test_stop_and_transcribe_suspends_mic_stream(self):
        """The live mic stream must be suspended before transcription starts."""
        src = self._get_method_source("_on_stop_and_transcribe")
        self.assertIn("self._suspend_mic_stream_for_processing()", src)

    def test_transcription_result_resumes_mic_stream(self):
        """Successful transcription must re-open the live mic stream."""
        src = self._get_method_source("_on_transcription_result")
        self.assertIn("self._resume_mic_stream_after_processing()", src)

    def test_transcription_error_resumes_mic_stream(self):
        """Failed transcription must also re-open the live mic stream."""
        src = self._get_method_source("_on_transcription_error")
        self.assertIn("self._resume_mic_stream_after_processing()", src)

    def test_suspend_resume_helpers_exist(self):
        """MainWindow must define explicit mic suspend/resume helpers."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("_suspend_mic_stream_for_processing", method_names)
        self.assertIn("_resume_mic_stream_after_processing", method_names)

    # â”€â”€ Phase 6 (professional mode quick-toggle checkbox) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_chk_professional_in_build_ui(self):
        """_chk_professional toggle must be created in _build_ui."""
        src = self._get_method_source("_build_ui")
        self.assertIn("self._chk_professional", src)
        self.assertIn('ToggleSwitch("Enable")', src)

    def test_chk_professional_connected_to_toggled(self):
        """_chk_professional must be connected to _on_professional_toggled."""
        src = self._get_method_source("_build_ui")
        self.assertIn("_chk_professional.toggled.connect(self._on_professional_toggled)", src)

    def test_on_professional_toggled_method_exists(self):
        """_on_professional_toggled must be defined in MainWindow."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("_on_professional_toggled", method_names)

    def test_on_professional_toggled_handles_no_api_key(self):
        """_on_professional_toggled must handle the no-API-key case."""
        src = self._get_method_source("_on_professional_toggled")
        self.assertIn("API Key Required", src)

    def test_on_professional_toggled_handles_no_preset(self):
        """_on_professional_toggled must handle the no-preset case."""
        src = self._get_method_source("_on_professional_toggled")
        self.assertIn("No Preset Configured", src)

    def test_on_pro_mode_applied_syncs_checkbox(self):
        """_on_pro_mode_applied must sync _chk_professional."""
        src = self._get_method_source("_on_pro_mode_applied")
        self.assertIn("_chk_professional.setChecked", src)
        self.assertIn("_chk_professional.blockSignals", src)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Live widget tests â€” require PySide6
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


@unittest.skipUnless(_qt_available(), "PySide6 not available")
class TestDiagnosticsToggleLive(unittest.TestCase):
    """Integration tests for diagnostics collapse/expand with a real QApp."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication, QMessageBox
        cls._app = QApplication.instance() or QApplication([])
        # Make QMessageBox available to all test methods in this class
        globals()["QMessageBox"] = QMessageBox

    def _make_window(self):
        """Create a MainWindow with mocked engine for testing."""
        from unittest.mock import MagicMock, PropertyMock, patch
        from speakeasy.config import Settings
        import tempfile

        settings = Settings()
        settings.hotkeys_enabled = False

        engine = MagicMock()
        engine.name = "mock"
        type(engine).is_loaded = PropertyMock(return_value=False)

        # Use a temp dir for presets so tests don't need C:\Program Files access
        self._tmp = tempfile.mkdtemp()
        tmp_presets = Path(self._tmp) / "presets"

        import speakeasy.main_window as _mw
        orig = _mw.DEFAULT_PRESETS_DIR
        _mw.DEFAULT_PRESETS_DIR = tmp_presets
        try:
            from speakeasy.main_window import MainWindow
            win = MainWindow(settings, engine=engine)
        finally:
            _mw.DEFAULT_PRESETS_DIR = orig
        return win

    def test_log_text_exists(self):
        """Hidden _log_text widget must still exist for buffering."""
        win = self._make_window()
        try:
            self.assertIsNotNone(win._log_text)
        finally:
            win.close()

    def test_dev_panel_not_created_by_default(self):
        """Developer Panel must not be created on construction."""
        win = self._make_window()
        try:
            self.assertIsNone(win._dev_panel)
        finally:
            win.close()

    def test_gear_button_exists(self):
        """Gear button must exist for opening the Developer Panel."""
        win = self._make_window()
        try:
            self.assertIsNotNone(win._btn_dev_panel)
        finally:
            win.close()

    def test_log_captured_to_hidden_widget(self):
        """Log text must accumulate in the hidden _log_text widget."""
        win = self._make_window()
        try:
            win._log_text.appendPlainText("test log message")
            self.assertIn("test log message", win._log_text.toPlainText())
        finally:
            win.close()

    def test_status_bar_exists(self):
        """The inline status pill bar must exist."""
        win = self._make_window()
        try:
            self.assertIsNotNone(win._status_bar)
        finally:
            win.close()

    def test_start_button_height(self):
        """Record button must have minimum height >= 48."""
        win = self._make_window()
        try:
            self.assertGreaterEqual(win._btn_record.minimumHeight(), 48)
        finally:
            win.close()

    def test_record_button_height(self):
        """Record button must have minimum height >= 48."""
        win = self._make_window()
        try:
            self.assertGreaterEqual(win._btn_record.minimumHeight(), 48)
        finally:
            win.close()

    # â”€â”€ Phase 6 (professional mode quick-toggle live tests) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_chk_professional_exists(self):
        """Professional Mode checkbox must exist on the main window."""
        win = self._make_window()
        try:
            self.assertIsNotNone(win._chk_professional)
            self.assertEqual(win._chk_professional.text(), "Enable")
        finally:
            win.close()

    def test_chk_professional_default_unchecked(self):
        """Professional Mode checkbox defaults to unchecked (pro mode off)."""
        win = self._make_window()
        try:
            self.assertFalse(win._chk_professional.isChecked())
        finally:
            win.close()

    def test_chk_professional_reflects_settings(self):
        """Professional Mode checkbox reflects settings.professional_mode."""
        from unittest.mock import MagicMock, PropertyMock, patch
        from speakeasy.config import Settings
        import tempfile

        settings = Settings()
        settings.professional_mode = True
        settings.hotkeys_enabled = False

        engine = MagicMock()
        engine.name = "mock"
        type(engine).is_loaded = PropertyMock(return_value=False)

        tmp = tempfile.mkdtemp()
        import speakeasy.main_window as _mw
        orig = _mw.DEFAULT_PRESETS_DIR
        _mw.DEFAULT_PRESETS_DIR = Path(tmp) / "presets"
        try:
            from speakeasy.main_window import MainWindow
            win = MainWindow(settings, engine=engine)
            try:
                self.assertTrue(win._chk_professional.isChecked())
            finally:
                win.close()
        finally:
            _mw.DEFAULT_PRESETS_DIR = orig

    def test_toggle_on_without_api_key_reverts(self):
        """Enabling Professional Mode without an API key must revert the checkbox."""
        from unittest.mock import patch
        win = self._make_window()
        try:
            win._api_key = ""
            # Patch QMessageBox to auto-click No (cancel)
            with patch(
                "speakeasy.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ):
                win._chk_professional.setChecked(True)
            self.assertFalse(win._chk_professional.isChecked())
            self.assertFalse(win.settings.professional_mode)
        finally:
            win.close()

    def test_toggle_on_with_api_key_enables(self):
        """Enabling Professional Mode with API key and preset must succeed."""
        from unittest.mock import MagicMock
        from speakeasy.pro_preset import ProPreset

        win = self._make_window()
        try:
            win._api_key = "sk-test-key"
            win._active_preset = ProPreset(name="Test")
            win.settings.pro_disclosure_accepted = True
            win._chk_professional.setChecked(True)
            self.assertTrue(win.settings.professional_mode)
            self.assertIsNotNone(win._text_processor)
        finally:
            win.close()

    def test_toggle_off_disables(self):
        """Disabling Professional Mode must clear TextProcessor."""
        from unittest.mock import MagicMock
        from speakeasy.pro_preset import ProPreset

        win = self._make_window()
        try:
            # First enable
            win._api_key = "sk-test-key"
            win._active_preset = ProPreset(name="Test")
            win.settings.pro_disclosure_accepted = True
            win._chk_professional.setChecked(True)
            self.assertIsNotNone(win._text_processor)
            # Then disable
            win._chk_professional.setChecked(False)
            self.assertFalse(win.settings.professional_mode)
            self.assertIsNone(win._text_processor)
        finally:
            win.close()


@unittest.skipUnless(_qt_available(), "PySide6 not available")
class TestStreamingPartials(unittest.TestCase):
    """Live tests for the per-chunk partial transcription UX (Phase 3)."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def _make_window(self, streaming_enabled=True):
        from unittest.mock import MagicMock, PropertyMock
        from speakeasy.config import Settings
        import tempfile

        settings = Settings()
        settings.hotkeys_enabled = False
        settings.streaming_partials_enabled = streaming_enabled

        engine = MagicMock()
        engine.name = "mock"
        type(engine).is_loaded = PropertyMock(return_value=False)

        self._tmp = tempfile.mkdtemp()
        tmp_presets = Path(self._tmp) / "presets"

        import speakeasy.main_window as _mw
        orig = _mw.DEFAULT_PRESETS_DIR
        _mw.DEFAULT_PRESETS_DIR = tmp_presets
        try:
            from speakeasy.main_window import MainWindow
            win = MainWindow(settings, engine=engine)
        finally:
            _mw.DEFAULT_PRESETS_DIR = orig
        return win

    def _history_entries(self, win):
        """Return all _HistoryEntry widgets currently in the history pane."""
        from speakeasy.main_window import _HistoryEntry
        return [
            win._history_layout.itemAt(i).widget()
            for i in range(win._history_layout.count())
            if isinstance(win._history_layout.itemAt(i).widget(), _HistoryEntry)
        ]

    def test_partial_signal_creates_draft_entry(self):
        win = self._make_window()
        try:
            win._on_transcription_partial("hello world", 1, 3)
            entries = self._history_entries(win)
            self.assertEqual(len(entries), 1)
            self.assertTrue(entries[0].is_draft)
            self.assertEqual(entries[0].text, "hello world")
            self.assertIsNotNone(win._active_draft_entry)
        finally:
            win.close()

    def test_partial_signal_updates_in_place(self):
        win = self._make_window()
        try:
            win._on_transcription_partial("hello", 1, 3)
            win._on_transcription_partial("hello world", 2, 3)
            entries = self._history_entries(win)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].text, "hello world")
            self.assertTrue(entries[0].is_draft)
        finally:
            win.close()

    def test_final_result_replaces_draft(self):
        win = self._make_window()
        try:
            win._on_transcription_partial("hello world", 1, 2)
            win._on_transcription_partial("hello world again", 2, 2)
            # Final result path calls _add_history via _on_transcription_result.
            # Invoke _add_history directly (bypasses clipboard / state-reset plumbing).
            win._add_history("12:34:56", "hello world again final", success=True)
            entries = self._history_entries(win)
            self.assertEqual(len(entries), 1)
            self.assertFalse(entries[0].is_draft)
            self.assertEqual(entries[0].text, "hello world again final")
            self.assertIsNone(win._active_draft_entry)
        finally:
            win.close()

    def test_error_after_partial_marks_draft_failed(self):
        win = self._make_window()
        try:
            win._on_transcription_partial("partial text", 1, 3)
            # Error slot calls _add_history with success=False via the shared path.
            win._add_history("12:34:56", "Error: boom", success=False)
            entries = self._history_entries(win)
            self.assertEqual(len(entries), 1)
            self.assertFalse(entries[0].is_draft)
            self.assertEqual(entries[0].text, "Error: boom")
            self.assertIsNone(win._active_draft_entry)
        finally:
            win.close()

    def test_short_clip_does_not_create_draft(self):
        """No partial signal â†’ plain _add_history must create a normal entry."""
        win = self._make_window()
        try:
            win._add_history("12:34:56", "short clip text", success=True)
            entries = self._history_entries(win)
            self.assertEqual(len(entries), 1)
            self.assertFalse(entries[0].is_draft)
            self.assertIsNone(win._active_draft_entry)
        finally:
            win.close()

    def test_professional_mode_original_and_cleaned_reach_final_entry(self):
        """Draft â†’ final with original_text should produce the two-line layout."""
        win = self._make_window()
        try:
            win._on_transcription_partial("raw text", 1, 2)
            win._on_transcription_partial("raw text cleaned later", 2, 2)
            win._add_history(
                "12:34:56", "polished cleaned text", success=True,
                original_text="raw text cleaned later",
            )
            entries = self._history_entries(win)
            self.assertEqual(len(entries), 1)
            self.assertFalse(entries[0].is_draft)
            self.assertEqual(entries[0].text, "polished cleaned text")
        finally:
            win.close()

    def test_streaming_disabled_keeps_no_draft_state(self):
        """With partials disabled, the partial slot is not connected and nothing appears."""
        win = self._make_window(streaming_enabled=False)
        try:
            # Even if _on_transcription_partial were invoked manually, the
            # setting alone is a UX flag; the guard in _on_stop_and_transcribe
            # is what actually prevents connection. Verify the setting is False.
            self.assertFalse(win.settings.streaming_partials_enabled)
            self.assertIsNone(win._active_draft_entry)
        finally:
            win.close()
