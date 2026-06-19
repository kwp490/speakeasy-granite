"""Engine-layer error taxonomy.

These exceptions form the contract between the engine/service layer and the
UI.  The UI keys its error rendering off exception *types*, never off string
matching, so adding a new engine or transport does not require re-auditing
message parsing in the window code.
"""

from __future__ import annotations

from typing import Optional, Sequence


class EngineError(Exception):
    """Base class for all transcription-service errors."""


class ModelNotConfigured(EngineError):
    """No model source is configured (or the configured source is empty)."""


class ModelFilesMissing(EngineError):
    """The model directory exists but required files are missing or invalid."""

    def __init__(
        self,
        missing: Sequence[str] = (),
        invalid: Sequence[str] = (),
        message: Optional[str] = None,
    ) -> None:
        self.missing = tuple(missing)
        self.invalid = tuple(invalid)
        if message is None:
            parts = []
            if self.missing:
                parts.append(f"missing: {', '.join(self.missing)}")
            if self.invalid:
                parts.append(f"invalid: {', '.join(self.invalid)}")
            message = "Model files unavailable" + (
                f" ({'; '.join(parts)})" if parts else ""
            )
        super().__init__(message)


class ModelAuthRequired(EngineError):
    """The model requires authentication that is not available.

    Maps the downloader's ``EXIT_AUTH_REQUIRED`` exit code.
    """


class DeviceUnavailable(EngineError):
    """The requested compute device (e.g. ``cuda``) is not available."""


class InferenceTimeout(EngineError):
    """Transcription exceeded the configured timeout budget."""


class RemoteUnreachable(EngineError):
    """A remote transcription endpoint could not be reached."""

    def __init__(self, url: str, cause: Optional[BaseException] = None) -> None:
        self.url = url
        self.cause = cause
        message = f"Could not reach {url}"
        if cause is not None:
            message += f": {cause}"
        super().__init__(message)


class RemoteAuthFailed(EngineError):
    """A remote endpoint rejected the supplied bearer token (HTTP 401/403)."""


class RemoteVersionMismatch(EngineError):
    """A remote endpoint speaks a contract version this client does not support."""

    def __init__(self, server_version: int, client_version: int) -> None:
        self.server_version = server_version
        self.client_version = client_version
        super().__init__(
            f"Server is running contract v{server_version}; "
            f"this app supports v{client_version}."
        )
