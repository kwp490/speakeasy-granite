"""Central tooltip / accessibility-text registry.

Every interactive control in the user-facing surfaces (settings, AI writing
profiles, AI providers, history and the main-window button row) must carry a
non-empty tooltip.  ``tests/test_tooltips.py`` enforces that rule by walking the
real widget trees.

This module is the canonical home for tooltip copy that is shared or wants a
stable identifier.  Controls may still set their tooltip inline, but new
controls should prefer :func:`apply_tooltip` so the text lives in one place and
is mirrored into the widget's accessible description for screen readers.

Keys use a ``<surface>.<control>`` dotted convention, e.g. ``"settings.device"``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PySide6.QtWidgets import QWidget


TOOLTIPS: dict[str, str] = {
    # --- Settings ---------------------------------------------------------
    "settings.device": "Choose the hardware used for transcription (CPU or GPU).",
    "settings.language": "Spoken language to transcribe. Auto-detect when set to Auto.",
    "settings.task": "Transcribe in the original language or translate to English.",
    "settings.translation_target": "Target language when translating.",
    "settings.keyword_bias": "Comma-separated words or names to bias recognition toward.",
    "settings.punctuation": "Insert punctuation and capitalisation automatically.",
    "settings.formatting_style": "How recognised text is formatted before output.",
    "settings.microphone": "Input device used to capture your voice.",
    "settings.auto_copy": "Copy each transcription to the clipboard automatically.",
    "settings.auto_paste": "Paste each transcription into the focused app automatically.",
    "settings.hotkeys_enabled": "Enable global keyboard shortcuts.",
    "settings.hotkey_start": "Shortcut that starts/stops dictation.",
    "settings.hotkey_quit": "Shortcut that quits SpeakEasy.",
    "settings.hotkey_dev_panel": "Shortcut that toggles the Developer Panel.",
    "settings.apply": "Apply pending changes.",
    "settings.restore_defaults": "Reset every setting on this page to its default value.",
    # --- Advanced settings -----------------------------------------------
    "advanced.model_location.managed": "Use the model managed and updated by SpeakEasy.",
    "advanced.model_location.custom": "Use a model folder you provide on this machine.",
    "advanced.model_location.remote": "Connect to a remote transcription server.",
    "advanced.model_path": "Folder that contains the local model weights.",
    "advanced.browse": "Choose the folder that contains the model weights.",
    "advanced.remote_url": "URL of the remote transcription server.",
    "advanced.remote_token": "Authentication token for the remote server (optional).",
    "advanced.test_connection": "Check that the remote server is reachable.",
    "advanced.inference_timeout": "Maximum seconds to wait for a transcription result.",
    "advanced.silence_threshold": "Audio level below which input is treated as silence.",
    "advanced.silence_margin": "Extra silence kept around speech before trimming.",
    "advanced.sample_rate": "Audio capture sample rate in Hertz.",
    "advanced.clear_logs_on_exit": "Delete log files when the app exits.",
    # --- AI providers -----------------------------------------------------
    "providers.provider": "AI provider used for professional-mode rewriting.",
    "providers.api_key": "API key for the selected provider.",
    "providers.reveal": "Show or hide the API key.",
    "providers.paste": "Paste an API key from the clipboard.",
    "providers.validate": "Verify the API key with the provider.",
    "providers.remember": "Store the API key securely for next launch.",
    "providers.default_model": "Default model used for professional-mode rewriting.",
    # --- AI writing profiles (pro mode) ----------------------------------
    "pro.preset": "Active writing profile.",
    "pro.new_preset": "Create a new writing profile.",
    "pro.duplicate_preset": "Duplicate the selected writing profile.",
    "pro.delete_preset": "Delete the selected writing profile.",
    "pro.fix_tone": "Adjust tone while preserving meaning.",
    "pro.fix_grammar": "Correct grammar in the transcript.",
    "pro.fix_punctuation": "Fix punctuation in the transcript.",
    "pro.advanced": "Show advanced writing-profile options.",
    "pro.save": "Save changes to the active writing profile.",
    "pro.reset": "Discard changes and reload the saved profile.",
    # --- History ----------------------------------------------------------
    "history.clear": "Remove every entry from the history list.",
    "history.copy": "Copy this entry's text to the clipboard.",
    # --- Main window button row ------------------------------------------
    "main.record": "Start or stop dictation.",
    "main.settings": "Open settings.",
    "main.history": "Show transcription history.",
    "main.dev_panel": "Toggle the Developer Panel.",
}


def apply_tooltip(widget: "QWidget", key: str) -> None:
    """Set ``widget``'s tooltip (and accessible description) from the registry.

    Raises :class:`KeyError` for an unknown ``key`` so typos fail loudly in
    tests rather than silently leaving a control without help text.
    """
    text = TOOLTIPS[key]
    widget.setToolTip(text)
    widget.setAccessibleDescription(text)
