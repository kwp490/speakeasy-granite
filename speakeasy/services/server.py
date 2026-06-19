"""HTTP transcription server — the box behind ``speakeasy serve``.

Exposes the :class:`~speakeasy.core.contract.TranscriptionService` contract over
plain HTTP/1.1 + JSON under ``/v1`` so a :class:`~speakeasy.services.remote_client.RemoteEngineClient`
on another machine can drive transcription.  A single inference lock serializes
requests (the engine is single-stream anyway); a body-size cap bounds memory.

Security posture (see ``docs/REMOTE.md`` / ``SECURITY.md``):

* Binds to loopback (``127.0.0.1``) by default.  A non-loopback bind is refused
  unless ``allow_remote=True`` **and** a bearer token is set.
* When a token is configured every request must carry
  ``Authorization: Bearer <token>``; missing/wrong tokens get ``401``.
* No TLS termination is provided — run behind a VPN/stunnel for WAN use.

This module lives in ``services`` and stays torch-free at import scope; the heavy
engine import happens only when :func:`serve` builds a real Granite service.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .. import __version__
from ..core import wire
from ..core.contract import CONTRACT_VERSION, TranscriptionService
from ..core.errors import EngineError

log = logging.getLogger("speakeasy.server")

# 16 MB default body cap (~8 min of 16 kHz mono PCM16 WAV).
DEFAULT_MAX_BODY_BYTES = 16 * 1024 * 1024

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def generate_token() -> str:
    """Return a fresh URL-safe bearer token for ``--generate-token``."""
    return secrets.token_urlsafe(32)


def _is_loopback(host: str) -> bool:
    return host.strip().lower() in _LOOPBACK_HOSTS


class _TranscriptionHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the shared service + auth state."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        handler_class,
        *,
        service: TranscriptionService,
        token: Optional[str],
        max_body_bytes: int,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.service = service
        self.token = token
        self.max_body_bytes = max_body_bytes
        self.inference_lock = threading.Lock()


class TranscriptionRequestHandler(BaseHTTPRequestHandler):
    """Routes the ``/v1`` endpoints onto the wrapped service."""

    server_version = f"SpeakEasyASR/{__version__}"
    protocol_version = "HTTP/1.1"

    # ── Helpers ──────────────────────────────────────────────────────────

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib name
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def _authorized(self) -> bool:
        token = self.server.token  # type: ignore[attr-defined]
        if not token:
            return True
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        return secrets.compare_digest(header[len(prefix):], token)

    def _read_body(self) -> Optional[bytes]:
        length = int(self.headers.get("Content-Length", 0) or 0)
        max_body = self.server.max_body_bytes  # type: ignore[attr-defined]
        if length > max_body:
            self._send_error(413, f"Request body exceeds {max_body} bytes")
            return None
        return self.rfile.read(length) if length else b""

    # ── Routing ──────────────────────────────────────────────────────────

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        if not self._authorized():
            self._send_error(401, "Missing or invalid bearer token")
            return
        if self.path == "/v1/health":
            self._handle_health()
        elif self.path == "/v1/capabilities":
            self._handle_capabilities()
        else:
            self._send_error(404, f"Unknown path: {self.path}")

    def do_POST(self) -> None:  # noqa: N802 - stdlib name
        if not self._authorized():
            self._send_error(401, "Missing or invalid bearer token")
            return
        if self.path == "/v1/transcribe":
            self._handle_transcribe()
        else:
            self._send_error(404, f"Unknown path: {self.path}")

    # ── Endpoint handlers ────────────────────────────────────────────────

    def _handle_health(self) -> None:
        service: TranscriptionService = self.server.service  # type: ignore[attr-defined]
        try:
            health = service.health()
            descriptor = service.descriptor()
        except Exception as exc:  # noqa: BLE001 - report rather than crash
            self._send_error(500, f"health check failed: {exc}")
            return
        self._send_json(
            200,
            {
                "status": health.status,
                "engine": descriptor.name,
                "device": health.device,
                "model_loaded": health.model_loaded,
                "app_version": descriptor.version,
                "contract_version": CONTRACT_VERSION,
            },
        )

    def _handle_capabilities(self) -> None:
        service: TranscriptionService = self.server.service  # type: ignore[attr-defined]
        try:
            caps = service.capabilities()
        except Exception as exc:  # noqa: BLE001
            self._send_error(500, f"capabilities failed: {exc}")
            return
        self._send_json(200, wire.capabilities_to_dict(caps))

    def _handle_transcribe(self) -> None:
        body = self._read_body()
        if body is None:
            return
        if not body:
            self._send_error(400, "Empty request body (expected WAV audio)")
            return

        raw_options = self.headers.get("X-SpeakEasy-Options", "")
        try:
            options_dict = json.loads(raw_options) if raw_options else {}
            options = wire.options_from_dict(options_dict)
        except (ValueError, TypeError) as exc:
            self._send_error(400, f"Invalid options header: {exc}")
            return

        try:
            audio, sample_rate = wire.wav_bytes_to_audio(body)
        except Exception as exc:  # noqa: BLE001 - malformed audio is a client error
            self._send_error(400, f"Could not decode WAV body: {exc}")
            return
        if sample_rate != wire.TARGET_SR:
            self._send_error(
                400,
                f"Audio must be {wire.TARGET_SR} Hz mono PCM16; got {sample_rate} Hz",
            )
            return

        service: TranscriptionService = self.server.service  # type: ignore[attr-defined]
        lock: threading.Lock = self.server.inference_lock  # type: ignore[attr-defined]
        with lock:
            try:
                result = service.transcribe(audio, options)
            except EngineError as exc:
                self._send_json(
                    409, {"error": str(exc), "error_type": type(exc).__name__}
                )
                return
            except Exception as exc:  # noqa: BLE001
                self._send_error(500, f"transcription failed: {exc}")
                return
        self._send_json(200, wire.result_to_dict(result))


def create_server(
    service: TranscriptionService,
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    token: Optional[str] = None,
    allow_remote: bool = False,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> _TranscriptionHTTPServer:
    """Build (but do not start) a transcription HTTP server.

    Raises ``ValueError`` for an unsafe configuration (non-loopback bind without
    ``allow_remote`` and a token).
    """
    if not _is_loopback(host):
        if not allow_remote:
            raise ValueError(
                f"Refusing to bind non-loopback host {host!r} without allow_remote=True"
            )
        if not token:
            raise ValueError(
                f"A bearer token is required to bind non-loopback host {host!r}"
            )
    return _TranscriptionHTTPServer(
        (host, port),
        TranscriptionRequestHandler,
        service=service,
        token=token,
        max_body_bytes=max_body_bytes,
    )


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    device: str = "cpu",
    model_dir: Optional[str] = None,
    token: Optional[str] = None,
    allow_remote: bool = False,
    engine: str = "granite",
) -> int:
    """Build a real engine service, load the model, and serve until interrupted.

    Returns a process exit code.
    """
    from ..config import DEFAULT_MODELS_DIR
    from ..core.model_source import LocalDirSource
    from ..engines.registry import create_service
    from .provisioning import ensure_model

    resolved_dir = model_dir or DEFAULT_MODELS_DIR
    source = LocalDirSource(path=resolved_dir)

    log.info("Provisioning %s model at %s", engine, resolved_dir)
    try:
        ensure_model(source, engine_name=engine, progress_format="text")
    except EngineError as exc:
        log.error("Model provisioning failed: %s", exc)
        return 1

    service = create_service(engine)
    log.info("Loading %s model on %s", engine, device)
    try:
        service.load(source, device)
    except EngineError as exc:
        log.error("Model load failed: %s", exc)
        return 1

    try:
        server = create_server(
            service,
            host,
            port,
            token=token,
            allow_remote=allow_remote,
        )
    except ValueError as exc:
        log.error("%s", exc)
        return 2

    bound_host, bound_port = server.server_address[:2]
    log.info(
        "SpeakEasy ASR server listening on http://%s:%s (token %s)",
        bound_host,
        bound_port,
        "set" if token else "DISABLED",
    )
    if not token and not _is_loopback(host):
        log.warning("Serving without a token — this is only safe on loopback")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down server")
    finally:
        server.shutdown()
        server.server_close()
        try:
            service.unload()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
    return 0
