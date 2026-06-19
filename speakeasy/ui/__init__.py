"""UI layer for SpeakEasy AI.

This package is the gradual migration target for the window/controller split
described in the rearchitecture plan (§9).  Modules here may import PySide6 but
must **not** import torch/transformers/librosa/accelerate at module scope — the
heavy ML stack stays behind the :class:`speakeasy.core.contract.TranscriptionService`
boundary.
"""

from __future__ import annotations

from .tooltips import TOOLTIPS, apply_tooltip

__all__ = ["TOOLTIPS", "apply_tooltip"]
