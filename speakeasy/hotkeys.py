"""
Global hotkey management.

Uses the Win32 ``RegisterHotKey`` API so only the registered chord is
delivered to the application — no low-level keyboard hook (WH_KEYBOARD_LL)
is installed.  Activation messages arrive as ``WM_HOTKEY`` in the Qt native
event loop and are dispatched as Qt signals for thread-safe UI updates.
"""

from __future__ import annotations

import ctypes
import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

# ── Win32 modifier flags ──────────────────────────────────────────────────────
_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008
_MOD_NOREPEAT = 0x4000  # suppress repeated WM_HOTKEY while key is held

# ── Application-defined hotkey IDs ───────────────────────────────────────────
_ID_TOGGLE = 1
_ID_QUIT = 2
_ID_DEV_PANEL = 3

# ── Virtual-key code table for named keys ────────────────────────────────────
_VK_NAMED: dict[str, int] = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D, "ins": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}

_MODIFIER_NAMES = {"ctrl", "control", "alt", "shift", "win", "windows"}


def _parse_hotkey(hotkey_str: str) -> tuple[int, int]:
    """Parse a hotkey string like ``ctrl+alt+p`` into ``(mods, vk)``.

    Returns a ``(modifier_flags, virtual_key_code)`` tuple suitable for
    passing directly to ``RegisterHotKey``.  Always includes ``_MOD_NOREPEAT``.
    Raises ``ValueError`` for unknown or missing key components.
    """
    parts = [p.strip().lower() for p in hotkey_str.split("+")]
    mods = _MOD_NOREPEAT
    vk: Optional[int] = None

    for part in parts:
        if part in ("ctrl", "control"):
            mods |= _MOD_CONTROL
        elif part == "alt":
            mods |= _MOD_ALT
        elif part == "shift":
            mods |= _MOD_SHIFT
        elif part in ("win", "windows"):
            mods |= _MOD_WIN
        elif part in _VK_NAMED:
            vk = _VK_NAMED[part]
        elif len(part) == 1 and part.isalpha():
            vk = ord(part.upper())
        elif len(part) == 1 and part.isdigit():
            vk = ord(part)
        else:
            raise ValueError(f"Unknown hotkey component: {part!r}")

    if vk is None:
        raise ValueError(f"No key (non-modifier) found in hotkey string: {hotkey_str!r}")

    return mods, vk


class HotkeyManager(QObject):
    """Registers/unregisters global hotkeys and emits Qt signals on activation.

    Uses ``RegisterHotKey`` / ``UnregisterHotKey`` — only the configured
    chords are delivered; no global keyboard hook is installed.
    ``WM_HOTKEY`` messages from the Qt native event loop must be forwarded
    to :meth:`handle_wm_hotkey` by the main window's ``nativeEvent`` handler.
    """

    toggle_requested = Signal()
    quit_requested = Signal()
    dev_panel_toggle_requested = Signal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._enabled = False
        self._hwnd: int = 0
        self._hotkey_start: Optional[str] = None
        self._hotkey_quit: Optional[str] = None
        self._hotkey_dev_panel: Optional[str] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def register(
        self,
        hotkey_start: str = "ctrl+alt+p",
        hotkey_quit: str = "ctrl+alt+q",
        hwnd: int = 0,
        hotkey_dev_panel: str = "ctrl+alt+d",
    ) -> None:
        """Register the dictation hotkeys against *hwnd*.  Safe to call repeatedly.

        Pass ``hwnd=int(self.winId())`` from the main window.  If *hwnd* is 0
        registration is skipped (safe for unit tests that have no native window).
        """
        self._hotkey_start = hotkey_start
        self._hotkey_quit = hotkey_quit
        self._hotkey_dev_panel = hotkey_dev_panel
        self._hwnd = hwnd
        self.unregister()

        if hwnd == 0:
            log.debug("RegisterHotKey skipped: no native window handle (hwnd=0)")
            return

        try:
            mods_toggle, vk_toggle = _parse_hotkey(hotkey_start)
            mods_quit, vk_quit = _parse_hotkey(hotkey_quit)
            mods_dev, vk_dev = _parse_hotkey(hotkey_dev_panel)
        except ValueError:
            log.error("Failed to parse hotkey strings", exc_info=True)
            return

        user32 = ctypes.windll.user32
        ok_toggle = user32.RegisterHotKey(hwnd, _ID_TOGGLE, mods_toggle, vk_toggle)
        ok_quit = user32.RegisterHotKey(hwnd, _ID_QUIT, mods_quit, vk_quit)
        ok_dev = user32.RegisterHotKey(hwnd, _ID_DEV_PANEL, mods_dev, vk_dev)

        if ok_toggle and ok_quit and ok_dev:
            self._enabled = True
            log.info("Hotkeys registered: record=%s  quit=%s  dev_panel=%s", hotkey_start, hotkey_quit, hotkey_dev_panel)
        else:
            # Partial registration — clean up to stay consistent
            user32.UnregisterHotKey(hwnd, _ID_TOGGLE)
            user32.UnregisterHotKey(hwnd, _ID_QUIT)
            user32.UnregisterHotKey(hwnd, _ID_DEV_PANEL)
            log.error(
                "RegisterHotKey failed (toggle=%s, quit=%s, dev_panel=%s) — hotkeys unavailable",
                bool(ok_toggle),
                bool(ok_quit),
                bool(ok_dev),
            )

    def unregister(self) -> None:
        """Unregister all hotkeys."""
        if not self._enabled:
            return
        user32 = ctypes.windll.user32
        user32.UnregisterHotKey(self._hwnd, _ID_TOGGLE)
        user32.UnregisterHotKey(self._hwnd, _ID_QUIT)
        user32.UnregisterHotKey(self._hwnd, _ID_DEV_PANEL)
        self._enabled = False
        log.info("Hotkeys unregistered")

    def re_register(self) -> None:
        """Re-register hotkeys using previously saved bindings.

        Call after system resume from sleep as a safety measure, e.g. after
        an RDP reconnect or session switch.
        """
        if self._hotkey_start is not None:
            log.info("Re-registering hotkeys after system resume")
            self.register(
                self._hotkey_start,
                self._hotkey_quit,
                self._hwnd,
                hotkey_dev_panel=self._hotkey_dev_panel or "ctrl+alt+d",
            )

    def handle_wm_hotkey(self, hotkey_id: int) -> None:
        """Dispatch a ``WM_HOTKEY`` message received by the native event loop."""
        if hotkey_id == _ID_TOGGLE:
            self.toggle_requested.emit()
        elif hotkey_id == _ID_QUIT:
            self.quit_requested.emit()
        elif hotkey_id == _ID_DEV_PANEL:
            self.dev_panel_toggle_requested.emit()

    @property
    def enabled(self) -> bool:
        return self._enabled

