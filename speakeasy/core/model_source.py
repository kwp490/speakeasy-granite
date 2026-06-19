"""Discriminated model-source schema.

Replaces the bare ``model_path`` string with a typed union that distinguishes a
managed location, a user-chosen local/UNC/removable directory, and a remote
``speakeasy serve`` endpoint.  Lives in ``core`` so both the UI and the
services layer can parse/serialize it without importing each other.

Security note: remote auth tokens are NEVER stored on a :class:`RemoteSource`
or serialized to ``settings.json``.  Only ``auth_token_ref`` (a pointer to the
OS keyring) is persisted; the token itself is fetched from keyring at use time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Union

# Path classification results (used by the UI for badges).
PATH_UNC = "unc"
PATH_REMOVABLE = "removable"
PATH_FIXED = "fixed"
PATH_UNKNOWN = "unknown"

# Windows GetDriveTypeW return codes.
_DRIVE_REMOVABLE = 2
_DRIVE_FIXED = 3
_DRIVE_REMOTE = 4


@dataclass(frozen=True)
class ManagedSource:
    """App-provisioned location under %ProgramData% (the default)."""

    path: str = ""
    type: str = "managed"


@dataclass(frozen=True)
class LocalDirSource:
    """A user-chosen folder (local disk, removable drive, or UNC share)."""

    path: str = ""
    type: str = "local_dir"


@dataclass(frozen=True)
class RemoteSource:
    """A remote ``speakeasy serve`` endpoint.

    The bearer token is held in the OS keyring, never here.
    """

    url: str = ""
    auth_token_ref: str = "keyring"
    verify_tls: bool = True
    timeout_s: float = 10.0
    type: str = "remote"


ModelSource = Union[ManagedSource, LocalDirSource, RemoteSource]


def parse(data: object) -> ModelSource:
    """Build a :data:`ModelSource` from a deserialized ``settings.json`` dict.

    Raises ``ValueError`` on an unknown ``type`` or an invalid remote URL.
    """
    if not isinstance(data, dict):
        raise ValueError(f"model_source must be a mapping, got {type(data).__name__}")

    kind = data.get("type")
    if kind == "managed":
        return ManagedSource(path=str(data.get("path", "")))
    if kind == "local_dir":
        return LocalDirSource(path=str(data.get("path", "")))
    if kind == "remote":
        url = str(data.get("url", "")).strip()
        _validate_remote_url(url)
        return RemoteSource(
            url=url,
            auth_token_ref=str(data.get("auth_token_ref", "keyring")),
            verify_tls=bool(data.get("verify_tls", True)),
            timeout_s=float(data.get("timeout_s", 10.0)),
        )
    raise ValueError(f"Unknown model_source type: {kind!r}")


def to_dict(source: ModelSource) -> dict:
    """Serialize a :data:`ModelSource` for ``settings.json``.

    Never includes a token — only ``auth_token_ref`` for remote sources.
    """
    if isinstance(source, ManagedSource):
        return {"type": "managed", "path": source.path}
    if isinstance(source, LocalDirSource):
        return {"type": "local_dir", "path": source.path}
    if isinstance(source, RemoteSource):
        return {
            "type": "remote",
            "url": source.url,
            "auth_token_ref": source.auth_token_ref,
            "verify_tls": source.verify_tls,
            "timeout_s": source.timeout_s,
        }
    raise TypeError(f"Not a ModelSource: {type(source).__name__}")


def _validate_remote_url(url: str) -> None:
    """Reject non-http(s) schemes (e.g. ``file://``) and empty URLs."""
    if not url:
        raise ValueError("Remote model_source requires a non-empty url")
    lowered = url.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise ValueError(
            f"Remote model_source url must be http(s), got: {url!r}"
        )


def classify_path(path: str) -> str:
    """Categorize a filesystem path for UI badges.

    Returns one of :data:`PATH_UNC`, :data:`PATH_REMOVABLE`,
    :data:`PATH_FIXED`, or :data:`PATH_UNKNOWN`.  UNC detection is purely
    syntactic (handles ``\\\\server\\share`` and the ``\\\\?\\UNC\\`` long-path
    prefix); drive-type detection uses ``GetDriveTypeW`` on Windows only.
    """
    p = (path or "").strip()
    if not p:
        return PATH_UNKNOWN

    normalized = p.replace("/", "\\")

    # Long-path UNC prefix: \\?\UNC\server\share
    if normalized.upper().startswith("\\\\?\\UNC\\"):
        return PATH_UNC
    # Long-path local prefix: \\?\C:\... — strip prefix, fall through to drive
    if normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    # Plain UNC: \\server\share
    elif normalized.startswith("\\\\"):
        return PATH_UNC

    return _classify_drive(normalized)


def _classify_drive(path: str) -> str:
    """Best-effort drive-type classification (Windows only)."""
    if os.name != "nt":
        return PATH_UNKNOWN
    drive = os.path.splitdrive(path)[0]
    if not drive:
        return PATH_UNKNOWN
    try:
        import ctypes

        root = drive + "\\"
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
    except Exception:  # pragma: no cover - defensive
        return PATH_UNKNOWN

    if drive_type == _DRIVE_REMOTE:
        return PATH_UNC
    if drive_type == _DRIVE_REMOVABLE:
        return PATH_REMOVABLE
    if drive_type == _DRIVE_FIXED:
        return PATH_FIXED
    return PATH_UNKNOWN
