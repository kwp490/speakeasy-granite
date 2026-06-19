"""Service layer — adapters that present engines as a ``TranscriptionService``.

The UI obtains a :class:`~speakeasy.core.contract.TranscriptionService` from
this package and never touches a concrete engine, torch, or transformers.
"""

from __future__ import annotations

from .inprocess import InProcessEngineService
from .provisioning import ensure_model, model_health, model_local_path
from .remote_client import (
    RemoteEngineClient,
    delete_remote_token,
    load_remote_token,
    save_remote_token,
)

__all__ = [
    "InProcessEngineService",
    "RemoteEngineClient",
    "ensure_model",
    "model_health",
    "model_local_path",
    "load_remote_token",
    "save_remote_token",
    "delete_remote_token",
]
