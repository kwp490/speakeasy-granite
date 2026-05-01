"""
Professional Mode text processor — OpenAI API integration.

Cleans up dictated text by fixing tone, grammar, and punctuation
via the OpenAI chat-completion API.  The API key is held **only** in
memory and is never logged, printed, or persisted to disk by this module.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Optional

from openai import AuthenticationError, OpenAI, OpenAIError

if TYPE_CHECKING:
    from .pro_preset import ProPreset

log = logging.getLogger(__name__)

_KEYRING_SERVICE = "speakeasy"
_KEYRING_SERVICE_LEGACY = "dictator"  # migration fallback from dictat0r.AI
_KEYRING_USERNAME = "openai_api_key"

# Timeout for API requests (connect, read) in seconds.
_REQUEST_TIMEOUT = 15.0


def _sanitize_error(exc: BaseException, api_key: str) -> str:
    """Return an error message with the API key redacted."""
    msg = str(exc)
    if api_key:
        msg = msg.replace(api_key, "***")
    return msg


def _build_system_prompt(
    fix_tone: bool,
    fix_grammar: bool,
    fix_punctuation: bool,
    *,
    custom_prompt: str = "",
    vocabulary: str = "",
) -> str:
    """Build the system prompt from the enabled cleanup flags.

    When *custom_prompt* is supplied (from a preset), it is a complete
    standalone system prompt and is used directly without wrapping.
    Adding generic numbered rules (e.g. "Fix grammar errors.") on top of
    a persona-based custom prompt produces conflicting instructions —
    for example, "Fix grammar errors." overrides a preset that intentionally
    uses inverted grammar or fragmented phrasing.

    *vocabulary* is a comma/newline-separated list of terms that the model
    must preserve verbatim; it is appended to whichever prompt path is used.
    """
    vocab_suffix = ""
    if vocabulary and vocabulary.strip():
        terms = [
            t.strip()
            for t in re.split(r"[,\n]+", vocabulary)
            if t.strip()
        ]
        if terms:
            term_list = ", ".join(terms)
            vocab_suffix = f"\n\nPreserve these terms exactly as written: {term_list}"

    # When a complete custom prompt is provided, use it as-is.  Appending
    # generic fix_grammar / fix_punctuation rules would conflict with presets
    # that intentionally use unconventional grammar or sentence structure.
    if custom_prompt and custom_prompt.strip():
        return custom_prompt.strip() + vocab_suffix

    # No custom prompt — build a simple numbered-rules prompt from flags.
    rules: list[str] = []
    if fix_tone:
        rules.append(
            "Make the tone professional and neutral. Remove emotional, "
            "aggressive, or unprofessional language while preserving the "
            "original meaning and intent."
        )
    if fix_grammar:
        rules.append("Fix grammar errors.")
    if fix_punctuation:
        rules.append("Add proper punctuation and capitalization.")

    if not rules:
        # All flags off and no custom prompt — nothing to do.
        return ""

    numbered = "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1))
    prompt = (
        "You are a text cleanup assistant. Rewrite the following dictated "
        "text with these corrections:\n"
        f"{numbered}\n\n"
        "Preserve the original meaning and intent. "
        "Output only the corrected text, nothing else."
    )
    return prompt + vocab_suffix


class TextProcessor:
    """Send dictated text to OpenAI for professional cleanup.

    The *api_key* is stored only as an instance attribute in memory.
    It is **never** logged, printed, or included in error messages.
    """

    def __init__(self, api_key: str, model: str = "gpt-5.4-mini") -> None:
        self._api_key = api_key
        self._model = model
        self._client: Optional[OpenAI] = None
        # Cumulative token counters for Developer Panel throughput display
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._last_tok_per_sec: float = 0.0
        self._last_call_time: float = 0.0  # monotonic timestamp of last result
        # Monotonically increasing counter — bumped after every successful
        # API completion so the Developer Panel sparkline can dedupe samples
        # between resource-monitor polls.
        self._call_seq: int = 0
        self._ensure_client()

    def _ensure_client(self) -> None:
        if self._client is None and self._api_key:
            self._client = OpenAI(
                api_key=self._api_key, timeout=_REQUEST_TIMEOUT
            )

    # ── Public API ────────────────────────────────────────────────────────

    def process(
        self,
        text: str,
        *,
        fix_tone: bool = True,
        fix_grammar: bool = True,
        fix_punctuation: bool = True,
        preset: ProPreset | None = None,
    ) -> str:
        """Clean up *text* according to the enabled flags or *preset*.

        If a *preset* is supplied its fields take priority over the
        individual flag arguments.

        Returns the cleaned text on success, or the original *text*
        unchanged on any API failure (graceful degradation).
        """
        if not text or not text.strip():
            return text

        # Resolve effective parameters from preset or kwargs
        if preset is not None:
            fix_tone = preset.fix_tone
            fix_grammar = preset.fix_grammar
            fix_punctuation = preset.fix_punctuation
            custom_prompt = preset.system_prompt
            vocabulary = preset.vocabulary
            model = preset.model or self._model
        else:
            custom_prompt = ""
            vocabulary = ""
            model = self._model

        system_prompt = _build_system_prompt(
            fix_tone, fix_grammar, fix_punctuation,
            custom_prompt=custom_prompt,
            vocabulary=vocabulary,
        )
        if not system_prompt:
            # All cleanup flags are disabled — pass through unchanged.
            return text

        self._ensure_client()
        if self._client is None:
            log.warning("Professional Mode: no API key configured — skipping cleanup")
            return text

        try:
            import time as _time
            _t0 = _time.monotonic()
            response = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                temperature=0.3,
            )
            _elapsed = _time.monotonic() - _t0

            # Track token usage for Developer Panel throughput display
            usage = getattr(response, "usage", None)
            in_tok = getattr(usage, "prompt_tokens", 0) or 0
            out_tok = getattr(usage, "completion_tokens", 0) or 0
            if in_tok == 0:
                # Rough estimate: ~4 chars per token for English
                in_tok = max(1, len(system_prompt + text) // 4)
            if out_tok == 0:
                content = response.choices[0].message.content or ""
                out_tok = max(1, len(content) // 4)
            self._total_input_tokens += in_tok
            self._total_output_tokens += out_tok
            self._last_tok_per_sec = out_tok / max(_elapsed, 0.001)
            self._last_call_time = _time.monotonic()
            self._call_seq += 1

            cleaned = response.choices[0].message.content
            return cleaned.strip() if cleaned else text
        except Exception as exc:
            log.error(
                "Professional Mode API error: %s",
                _sanitize_error(exc, self._api_key),
            )
            return text

    def validate_key(self) -> tuple[bool, str]:
        """Validate the API key with a lightweight API call.

        Returns ``(success, message)``.
        """
        self._ensure_client()
        if self._client is None:
            return False, "No API key provided"

        try:
            self._client.models.list()
            return True, "API key is valid"
        except AuthenticationError:
            return False, "Invalid API key"
        except OpenAIError as exc:
            return False, f"API error: {_sanitize_error(exc, self._api_key)}"
        except Exception as exc:
            return False, f"Unexpected error: {_sanitize_error(exc, self._api_key)}"

    @property
    def token_stats(self) -> tuple[float, int, int, int]:
        """Return ``(tok_per_sec, total_input_tokens, total_output_tokens, call_seq)``.

        ``tok_per_sec`` is the raw value from the most recent API call (no
        decay); ``call_seq`` increments by one per successful call so the
        Developer Panel sparkline can dedupe samples between polls.
        """
        return (
            self._last_tok_per_sec,
            self._total_input_tokens,
            self._total_output_tokens,
            self._call_seq,
        )


# ── Keyring helpers ──────────────────────────────────────────────────────────


def load_api_key_from_keyring() -> str:
    """Load the stored API key from Windows Credential Manager.

    Returns an empty string if *keyring* is unavailable or no key is stored.
    Migrates keys stored under the legacy service name ('dictator') to the
    new service name ('speakeasy') on first load.
    """
    try:
        import keyring

        value = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        if value:
            return value
        # Migration: check legacy service name from dictat0r.AI
        legacy_value = keyring.get_password(_KEYRING_SERVICE_LEGACY, _KEYRING_USERNAME)
        if legacy_value:
            # Migrate to new service name
            try:
                keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, legacy_value)
                keyring.delete_password(_KEYRING_SERVICE_LEGACY, _KEYRING_USERNAME)
                log.info("Migrated API key from legacy keyring service '%s' to '%s'",
                         _KEYRING_SERVICE_LEGACY, _KEYRING_SERVICE)
            except Exception:
                log.debug("Could not migrate API key to new keyring service", exc_info=True)
            return legacy_value
        return ""
    except Exception:
        log.debug("Could not load API key from keyring", exc_info=True)
        return ""


def save_api_key_to_keyring(api_key: str) -> None:
    """Persist the API key to Windows Credential Manager."""
    try:
        import keyring

        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, api_key)
    except Exception:
        log.warning("Could not save API key to keyring", exc_info=True)


def delete_api_key_from_keyring() -> None:
    """Remove the stored API key from Windows Credential Manager."""
    try:
        import keyring

        keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except Exception:
        # May raise if no credential exists — that's fine.
        log.debug("Could not delete API key from keyring", exc_info=True)
