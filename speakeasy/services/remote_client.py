"""Remote transcription client — the UI side of ``speakeasy serve``.

``RemoteEngineClient`` satisfies the :class:`~speakeasy.core.contract.TranscriptionService`
protocol by talking HTTP to a remote server instead of running an engine
locally.  It uses only the standard library (``urllib``) so the UI process can
construct it without torch/transformers installed.

Bearer tokens are read from / written to the OS keyring (service ``speakeasy``,
username ``remote_asr_token``), mirroring the pattern in
:mod:`speakeasy.text_processor`.  Tokens are never persisted in ``settings.json``
— only ``RemoteSource.auth_token_ref`` (a pointer) is.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Optional

import numpy as np

from .. import __version__
from ..core import wire
from ..core.contract import (
    CONTRACT_VERSION,
    EngineCapabilities,
    EngineDescriptor,
    EngineStats,
    HealthReport,
    LoadReport,
    TranscriptionOptions,
    TranscriptionResult,
)
from ..core.errors import (
    RemoteAuthFailed,
    RemoteUnreachable,
    RemoteVersionMismatch,
)
from ..core.model_source import RemoteSource

log = logging.getLogger("speakeasy.remote_client")

_KEYRING_SERVICE = "speakeasy"
_KEYRING_USERNAME = "remote_asr_token"


# ── Keyring helpers ──────────────────────────────────────────────────────────


def load_remote_token() -> str:
    """Return the stored remote bearer token, or ``""`` if none/unavailable."""
    try:
        import keyring

        return keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME) or ""
    except Exception:  # noqa: BLE001 - keyring may be unavailable
        log.debug("Could not load remote token from keyring", exc_info=True)
        return ""


def save_remote_token(token: str) -> None:
    """Persist the remote bearer token to the OS keyring."""
    try:
        import keyring

        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, token)
    except Exception:  # noqa: BLE001
        log.warning("Could not save remote token to keyring", exc_info=True)


def delete_remote_token() -> None:
    """Remove the stored remote bearer token from the OS keyring."""
    try:
        import keyring

        keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except Exception:  # noqa: BLE001 - may raise if no credential exists
        log.debug("Could not delete remote token from keyring", exc_info=True)


# ── Client ───────────────────────────────────────────────────────────────────


class RemoteEngineClient:
    """A :class:`TranscriptionService` backed by a remote HTTP endpoint."""

    def __init__(
        self,
        source: RemoteSource,
        *,
        token: Optional[str] = None,
        app_version: str = __version__,
    ) -> None:
        self._source = source
        self._base_url = source.url.rstrip("/")
        self._timeout = float(source.timeout_s)
        self._verify_tls = bool(source.verify_tls)
        # Explicit token wins; otherwise read from keyring at construction time.
        self._token = token if token is not None else load_remote_token()
        self._app_version = app_version

        self._loaded = False
        self._engine_name = "remote"
        self._server_device = ""
        # Stats accumulated locally from transcribe results (no server stats endpoint).
        self._total_tokens = 0
        self._total_audio_s = 0.0
        self._last_rtf = 0.0
        self._last_tps = 0.0
        self._inference_count = 0

    # ── Identity / capabilities ──────────────────────────────────────────

    def descriptor(self) -> EngineDescriptor:
        if self._engine_name == "remote":
            # Populate from the server on first use; tolerate unreachable.
            try:
                self._get_health()
            except RemoteUnreachable:
                pass
        return EngineDescriptor(
            name=self._engine_name,
            version=self._app_version,
            is_remote=True,
        )

    def capabilities(self) -> EngineCapabilities:
        data = self._request("GET", "/v1/capabilities")
        return wire.capabilities_from_dict(data)

    # ── Lifecycle ────────────────────────────────────────────────────────

    def load(self, source, device: str) -> LoadReport:
        """For a remote service, "load" verifies reachability + contract version.

        The model itself is loaded by the server at startup.  The ``source`` and
        ``device`` arguments are accepted for contract compatibility; the
        effective endpoint is the :class:`RemoteSource` this client was built
        with.
        """
        info = self._get_health()
        self._loaded = bool(info.get("model_loaded", False))
        self._server_device = str(info.get("device", ""))
        return LoadReport(
            device=self._server_device or device,
            load_seconds=0.0,
        )

    def unload(self) -> None:
        # A remote client never tears down the server's model; it only forgets
        # its own connection state.
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    # ── Inference ────────────────────────────────────────────────────────

    def transcribe(
        self, audio_16k: np.ndarray, options: TranscriptionOptions
    ) -> TranscriptionResult:
        wav = wire.audio_to_wav_bytes(audio_16k)
        headers = {
            "Content-Type": "audio/wav",
            "X-SpeakEasy-Options": json.dumps(wire.options_to_dict(options)),
        }
        data = self._request("POST", "/v1/transcribe", body=wav, headers=headers)
        result = wire.result_from_dict(data)

        self._total_tokens += result.tokens_generated
        self._total_audio_s += result.audio_s
        self._inference_count += 1
        self._last_rtf = result.realtime_factor
        if result.inference_s > 0:
            self._last_tps = result.tokens_generated / result.inference_s
        return result

    # ── Status ───────────────────────────────────────────────────────────

    def health(self) -> HealthReport:
        try:
            info = self._get_health()
        except RemoteUnreachable as exc:
            return HealthReport(
                status="unreachable", detail=str(exc), model_loaded=False
            )
        return HealthReport(
            status=str(info.get("status", "ok")),
            model_loaded=bool(info.get("model_loaded", False)),
            device=str(info.get("device", "")),
        )

    def stats(self) -> EngineStats:
        return EngineStats(
            tokens_per_second=self._last_tps,
            total_tokens=self._total_tokens,
            total_audio_seconds=self._total_audio_s,
            realtime_factor=self._last_rtf,
            inference_count=self._inference_count,
        )

    def test_connection(self) -> HealthReport:
        """Used by the Settings "Test connection" button.

        Performs ``GET /v1/health`` and surfaces auth/version/connection errors
        as typed exceptions for the caller to render.
        """
        info = self._get_health()
        return HealthReport(
            status=str(info.get("status", "ok")),
            detail=f"engine={info.get('engine')} device={info.get('device')}",
            model_loaded=bool(info.get("model_loaded", False)),
            device=str(info.get("device", "")),
        )

    # ── Internals ────────────────────────────────────────────────────────

    def _get_health(self) -> dict:
        info = self._request("GET", "/v1/health")
        server_version = int(info.get("contract_version", CONTRACT_VERSION))
        if server_version != CONTRACT_VERSION:
            raise RemoteVersionMismatch(server_version, CONTRACT_VERSION)
        name = info.get("engine")
        if name:
            self._engine_name = str(name)
        return info

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Optional[bytes] = None,
        headers: Optional[dict] = None,
    ) -> dict:
        url = self._base_url + path
        req_headers = dict(headers or {})
        if self._token:
            req_headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(
            url, data=body, headers=req_headers, method=method
        )

        context = None
        if url.lower().startswith("https://") and not self._verify_tls:
            import ssl

            context = ssl._create_unverified_context()

        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout, context=context
            ) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            self._raise_for_http_error(exc)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RemoteUnreachable(url, exc) from exc

        if not payload:
            return {}
        try:
            return json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RemoteUnreachable(url, exc) from exc

    def _raise_for_http_error(self, exc: "urllib.error.HTTPError") -> None:
        if exc.code in (401, 403):
            raise RemoteAuthFailed(
                f"Server rejected the token (HTTP {exc.code})."
            ) from exc
        detail = ""
        try:
            payload = exc.read()
            if payload:
                detail = json.loads(payload.decode("utf-8")).get("error", "")
        except Exception:  # noqa: BLE001 - best-effort error detail
            detail = ""
        raise RemoteUnreachable(
            exc.url or self._base_url,
            RuntimeError(detail or f"HTTP {exc.code}"),
        ) from exc
