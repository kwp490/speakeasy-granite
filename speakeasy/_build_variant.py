"""Build variant flag — ``"gpu"`` (default) or ``"cpu"``.

The active variant is resolved once at import. Frozen builds embed a one-line
marker file named ``_variant_tag`` at the bundle root (``sys._MEIPASS``), written
by the PyInstaller build from the ``--variant`` argument (see ``spec_common.py``).
Running from source — or any build without the marker — defaults to ``"gpu"``.

This replaces the previous scheme where the CPU spec live-patched this file's
source during Analysis: nothing mutates this tracked file anymore.
"""

from __future__ import annotations

import os
import sys

_VARIANTS = ("gpu", "cpu")


def _resolve_variant() -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        try:
            with open(os.path.join(base, "_variant_tag"), "r", encoding="utf-8") as fh:
                tag = fh.read().strip().lower()
        except OSError:
            tag = ""
        if tag in _VARIANTS:
            return tag
    return "gpu"


VARIANT = _resolve_variant()  # "gpu" (default) or "cpu"
