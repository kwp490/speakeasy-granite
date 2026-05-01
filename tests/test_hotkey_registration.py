"""Tests for hotkey registration — dev_panel hotkey defaults and parsing.

Uses the HotkeyManager without Win32 RegisterHotKey (hwnd=0 skips OS calls).
"""

from __future__ import annotations

import pytest

from speakeasy.config import Settings
from speakeasy.hotkeys import _parse_hotkey, HotkeyManager


class TestHotkeyDefaults:
    def test_hotkey_dev_panel_field_default(self):
        assert Settings().hotkey_dev_panel == "ctrl+alt+d"

    def test_parse_ctrl_alt_d(self):
        mods, vk = _parse_hotkey("ctrl+alt+d")
        # vk for 'D' is ord('D') = 68
        assert vk == ord("D")
        # mods should include CTRL (0x0002) and ALT (0x0001) and NOREPEAT (0x4000)
        assert mods & 0x0002  # CTRL
        assert mods & 0x0001  # ALT

    def test_parse_ctrl_shift_d(self):
        mods, vk = _parse_hotkey("ctrl+shift+d")
        assert vk == ord("D")
        assert mods & 0x0002  # CTRL
        assert mods & 0x0004  # SHIFT


class TestHotkeyManagerRegistration:
    def test_hotkey_manager_has_dev_panel_signal(self):
        mgr = HotkeyManager()
        assert hasattr(mgr, "dev_panel_toggle_requested")

    def test_register_with_hwnd_zero_is_safe(self):
        """Registering with hwnd=0 should not crash (skips Win32 calls)."""
        mgr = HotkeyManager()
        mgr.register(
            hotkey_start="ctrl+alt+p",
            hotkey_quit="ctrl+alt+q",
            hwnd=0,
            hotkey_dev_panel="ctrl+alt+d",
        )
        # No crash; hotkeys not actually registered (no hwnd)

    def test_handle_wm_hotkey_for_dev_panel(self, qtbot):
        """handle_wm_hotkey with ID 3 should emit dev_panel_toggle_requested."""
        mgr = HotkeyManager()
        # Must register first (even with hwnd=0) to set _enabled
        # But _enabled will be False with hwnd=0, so we force it
        mgr._enabled = True
        with qtbot.waitSignal(mgr.dev_panel_toggle_requested, timeout=1000):
            mgr.handle_wm_hotkey(3)  # _ID_DEV_PANEL = 3

    def test_handle_wm_hotkey_for_toggle(self, qtbot):
        mgr = HotkeyManager()
        mgr._enabled = True
        with qtbot.waitSignal(mgr.toggle_requested, timeout=1000):
            mgr.handle_wm_hotkey(1)  # _ID_TOGGLE = 1

    def test_handle_wm_hotkey_for_quit(self, qtbot):
        mgr = HotkeyManager()
        mgr._enabled = True
        with qtbot.waitSignal(mgr.quit_requested, timeout=1000):
            mgr.handle_wm_hotkey(2)  # _ID_QUIT = 2
