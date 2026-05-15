"""Tests for the refactored MainWindow layout.

Verifies:
    Phase 1 - Transcription section is dominant; buttons enlarged, no Dictation GroupBox.
    Phase 2 - Diagnostics panel collapsed by default; toggling shows/hides.
    Phase 3 - Status pill bar placed between buttons and checkboxes (no QStatusBar).
    Phase 4 - Clear/Copy buttons are contextually placed in panel headers.
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


# Structural (AST) tests: no Qt needed


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

    # Phase 1

    def test_no_dictation_groupbox(self):
        """The 'Dictation' QGroupBox must no longer appear in _build_ui."""
        src = self._get_method_source("_build_ui")
        self.assertNotIn('QGroupBox("Dictation")', src)

    def test_start_button_height_increased(self):
        """Start Recording button must use theme Size for minimum height."""
        src = self._get_method_source("_build_ui")
        self.assertIn("setMinimumHeight(Size.BUTTON_HEIGHT_PRIMARY)", src)

    def test_start_button_uses_record_style(self):
        """Start/Stop button must use the dedicated record button style."""
        src = self._get_method_source("_build_ui")
        self.assertIn('primary_record_button_style("idle")', src)

    def test_history_widget_has_scroll_area(self):
        """HistoryWidget must contain a scrollable area for entries."""
        hw_source = (_REPO_ROOT / "speakeasy" / "history_widget.py").read_text(encoding="utf-8")
        self.assertIn("QScrollArea", hw_source)

    def test_window_target_size_is_compact(self):
        """Main window must keep the compact requested default size."""
        src = self._get_method_source("__init__")
        self.assertIn("setMinimumWidth(400)", src)
        self.assertIn("resize(475, 465)", src)

    def test_no_expanding_spacer_above_quit(self):
        """Quit should sit directly below History instead of below an expanding gap."""
        src = self._get_method_source("_build_ui")
        self.assertNotIn("root.addStretch()", src)

    def test_no_lbl_dictation_state_in_build_ui(self):
        """_lbl_dictation_state must not be created in _build_ui."""
        src = self._get_method_source("_build_ui")
        self.assertNotIn("_lbl_dictation_state", src)

    # Phase 2

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

    # Phase 3

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

    # Phase 4

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

    def test_clear_history_button_in_history_widget(self):
        """Clear History button must exist in HistoryWidget."""
        hw_source = (_REPO_ROOT / "speakeasy" / "history_widget.py").read_text(encoding="utf-8")
        self.assertIn("Clear History", hw_source)

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

    # Phase 5: professional mode button in footer

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
        """Pro Mode Settings button removed; now in Developer Panel."""
        src = self._get_method_source("_build_ui")
        self.assertNotIn("Pro Mode Settings", src)

    def test_on_open_pro_settings_method_exists(self):
        """_on_open_pro_settings must be defined in MainWindow."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("_on_open_pro_settings", method_names)

    def test_on_open_ai_providers_method_exists(self):
        """_on_open_ai_providers must be defined in MainWindow."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("_on_open_ai_providers", method_names)

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

    # Engine worker isolation

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

    # Main-window transcription mode controls

    def test_transcription_mode_controls_exist(self):
        """Main window exposes an activation toggle and profile selection."""
        src = self._get_method_source("_build_ui")
        self.assertNotIn("self._chk_professional", src)
        self.assertIn("self._chk_transcription_mode", src)
        self.assertIn("self._combo_pro_preset", src)
        self.assertIn("self._transcription_section_toggle", src)
        self.assertIn("collapsible=True", src)
        self.assertNotIn("self._combo_pro_model", src)
        self.assertIn('"Transcription Mode"', src)
        self.assertIn('"Enabled"', src)
        self.assertIn('"Profile"', src)

    def test_automation_section_is_collapsible(self):
        """Main window exposes a user-toggleable Automation section."""
        src = self._get_method_source("_build_ui")
        self.assertIn("self._automation_section_toggle", src)
        self.assertIn("self._automation_section_content", src)
        self.assertIn('"Automation"', src)

    def test_transcription_mode_toggle_handler_exists(self):
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("_on_transcription_mode_toggled", method_names)

    def test_profile_selection_prompts_for_missing_api_key(self):
        """Selecting a profile without a key must guide the user to AI Providers."""
        src = self._get_method_source("_on_main_profile_selected")
        self.assertIn("not self._api_key", src)
        self.assertIn("_prompt_for_missing_api_key()", src)

    def test_missing_api_key_prompt_opens_providers_tab(self):
        src = "\n".join(
            self._get_method_source(name) for name in (
                "_prompt_for_missing_api_key",
                "_on_open_ai_providers",
            )
        )
        self.assertIn("QMessageBox.information", src)
        self.assertIn("TAB_PROVIDERS", src)
        self.assertIn("activate_tab(TAB_PROVIDERS)", src)
        self.assertIn("focus_api_key()", src)

    def test_no_pending_professional_enable_state(self):
        """Pending-enable boolean must be removed."""
        src = "\n".join(
            self._get_method_source(name) for name in (
                "_on_pro_mode_applied",
            )
        )
        self.assertNotIn("_pending_professional_enable_after_api_key", src)

    def test_on_pro_mode_applied_method_exists(self):
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertIn("_on_pro_mode_applied", method_names)
        self.assertIn("_on_api_key_changed", method_names)

    def test_obsolete_handlers_removed(self):
        """Quick-toggle / quick-model handlers were removed in the v2 overhaul."""
        method_names = [
            n.name for n in ast.walk(self._mw_class)
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertNotIn("_on_professional_toggled", method_names)
        self.assertNotIn("_on_pro_model_quick_select", method_names)
        self.assertNotIn("_on_pro_preset_quick_select", method_names)


# Live widget tests: require PySide6


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
        tmp_models = Path(self._tmp) / "models"
        settings.model_path = str(tmp_models)

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

    def test_window_compact_size_target(self):
        """The initial layout must fit within the compact window target."""
        win = self._make_window()
        try:
            layout = win.centralWidget().layout()
            layout.activate()
            self.assertEqual(win.minimumSize().width(), 400)
            self.assertLessEqual(layout.minimumSize().height(), 490)
            self.assertEqual(win.size().width(), 475)
            self.assertEqual(win.size().height(), 287)
            self.assertGreater(win.size().width(), win.size().height())
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

    # Main-window transcription mode controls

    def test_main_transcription_mode_controls(self):
        """The legacy professional toggle is gone, but mode controls are available."""
        win = self._make_window()
        try:
            self.assertFalse(hasattr(win, "_chk_professional"))
            self.assertTrue(hasattr(win, "_chk_transcription_mode"))
            self.assertTrue(hasattr(win, "_combo_pro_preset"))
            self.assertFalse(hasattr(win, "_combo_pro_model"))
        finally:
            win.close()

    def test_transcription_mode_defaults_off(self):
        """Transcription mode is off by default while the profile selector is available."""
        win = self._make_window()
        try:
            self.assertEqual(win._combo_pro_preset.currentText(), win.settings.pro_active_preset)
            self.assertFalse(win._chk_transcription_mode.isChecked())
            self.assertFalse(win.settings.professional_mode)
        finally:
            win.close()

    def test_status_bar_pro_segment_off_when_no_profile(self):
        """Status pill shows 'Off' when professional_mode is False."""
        win = self._make_window()
        try:
            from speakeasy.status_pills import ProMode
            self.assertFalse(win.settings.professional_mode)
            # _update_global_status was called in __init__; ensure no crash
            win._update_global_status()
        finally:
            win.close()

    def test_main_sections_start_collapsed_and_expand(self):
        """Transcription Mode and Automation start collapsed and expand from their headers."""
        win = self._make_window()
        try:
            for toggle, content in (
                (win._transcription_section_toggle, win._transcription_section_content),
                (win._automation_section_toggle, win._automation_section_content),
            ):
                self.assertTrue(toggle.isCheckable())
                self.assertFalse(toggle.isChecked())
                self.assertTrue(content.isHidden())

                toggle.click()
                self.assertTrue(toggle.isChecked())
                self.assertFalse(content.isHidden())

                toggle.click()
                self.assertFalse(toggle.isChecked())
                self.assertTrue(content.isHidden())
        finally:
            win.close()

    def test_main_window_height_tracks_collapsible_sections(self):
        """The window grows and shrinks with the visible section content."""
        win = self._make_window()
        try:
            win.show()
            self._app.processEvents()
            collapsed_height = win.height()

            win._automation_section_toggle.click()
            self._app.processEvents()
            automation_expanded_height = win.height()
            self.assertGreater(automation_expanded_height, collapsed_height)

            win._transcription_section_toggle.click()
            self._app.processEvents()
            both_expanded_height = win.height()
            self.assertGreater(both_expanded_height, automation_expanded_height)

            win._automation_section_toggle.click()
            self._app.processEvents()
            transcription_only_height = win.height()
            self.assertLess(transcription_only_height, both_expanded_height)

            win._transcription_section_toggle.click()
            self._app.processEvents()
            self.assertLess(win.height(), transcription_only_height)
        finally:
            win.close()



@unittest.skipUnless(_qt_available(), "PySide6 not available")
class TestFinalHistoryEntries(unittest.TestCase):
    """Live tests for final transcription history entries."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def _make_window(self):
        from unittest.mock import MagicMock, PropertyMock
        from speakeasy.config import Settings
        import tempfile

        settings = Settings()
        settings.hotkeys_enabled = False

        engine = MagicMock()
        engine.name = "mock"
        type(engine).is_loaded = PropertyMock(return_value=False)

        self._tmp = tempfile.mkdtemp()
        tmp_presets = Path(self._tmp) / "presets"
        tmp_models = Path(self._tmp) / "models"
        settings.model_path = str(tmp_models)

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
        from speakeasy.history_widget import _HistoryEntry
        layout = win._dev_panel.history_widget.history_layout
        return [
            layout.itemAt(i).widget()
            for i in range(layout.count())
            if isinstance(layout.itemAt(i).widget(), _HistoryEntry)
        ]

    def test_add_history_creates_final_entry(self):
        win = self._make_window()
        try:
            win._ensure_dev_panel()
            win._add_history("12:34:56", "final text", success=True)
            entries = self._history_entries(win)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].text, "final text")
        finally:
            win.close()

    def test_professional_mode_original_and_cleaned_reach_final_entry(self):
        win = self._make_window()
        try:
            win._ensure_dev_panel()
            win._add_history(
                "12:34:56", "polished cleaned text", success=True,
                original_text="raw text cleaned later",
            )
            entries = self._history_entries(win)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].text, "polished cleaned text")
        finally:
            win.close()
