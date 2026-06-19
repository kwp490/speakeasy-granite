"""Model provisioning — download / health / repair, decoupled from the engine.

Historically ``GraniteTranscribeEngine.load()`` reached back into
``speakeasy.model_downloader`` to auto-download missing weights, creating a
UI → engine → downloader cycle (coupling problem C-2).  Provisioning now lives
here: the UI calls :func:`ensure_model` *before* ``service.load()``; the engine
merely loads what is on disk and raises :class:`ModelFilesMissing` if anything
is absent.

This module is intentionally torch-free at import time.  ``model_downloader``
(stdlib-only at module scope) and ``huggingface_hub`` are imported lazily inside
the functions so the UI process can import ``speakeasy.services`` without the ML
stack installed.
"""

from __future__ import annotations

from ..core.errors import ModelAuthRequired, ModelFilesMissing, ModelNotConfigured
from ..core.model_source import (
    LocalDirSource,
    ManagedSource,
    ModelSource,
    RemoteSource,
)


def model_local_path(source: ModelSource) -> str:
    """Return the local directory a managed/local source resolves to.

    Raises :class:`ModelNotConfigured` for an empty path and :class:`ModelFilesMissing`
    (via the caller) is not raised here — this only resolves the path.  Remote
    sources have no local path and raise ``ModelNotConfigured``.
    """
    if isinstance(source, (ManagedSource, LocalDirSource)):
        if not source.path:
            raise ModelNotConfigured("Model source path is empty.")
        return source.path
    raise ModelNotConfigured(
        "Remote model sources are provisioned by the server, not locally."
    )


def model_health(source: ModelSource, *, engine_name: str = "granite"):
    """Return the on-disk :class:`ModelHealth` for a managed/local source."""
    from ..model_downloader import model_health as _model_health

    path = model_local_path(source)
    return _model_health(engine_name, path)


def ensure_model(
    source: ModelSource,
    *,
    engine_name: str = "granite",
    progress_callback=None,
    progress_format: str = "none",
):
    """Make sure the model for *source* is present on disk, downloading if needed.

    Returns the resulting :class:`~speakeasy.model_downloader.ModelHealth`.

    Raises
    ------
    ModelNotConfigured
        The source has no local path (remote source or empty path).
    ModelAuthRequired
        The repository is gated and anonymous download was refused.
    ModelFilesMissing
        The download failed or the model is still incomplete afterwards.
    """
    if isinstance(source, RemoteSource):
        raise ModelNotConfigured(
            "Remote model sources are provisioned by the server, not locally."
        )

    from ..model_downloader import (
        EXIT_AUTH_REQUIRED,
        EXIT_SUCCESS,
        download_model,
        model_health as _model_health,
    )

    path = model_local_path(source)

    health = _model_health(engine_name, path)
    if health.ready:
        return health

    rc = download_model(
        engine_name,
        path,
        progress_callback=progress_callback,
        progress_format=progress_format,
    )
    if rc == EXIT_AUTH_REQUIRED:
        raise ModelAuthRequired(
            f"The {engine_name} model requires authentication to download."
        )

    health = _model_health(engine_name, path)
    if rc != EXIT_SUCCESS or not health.ready:
        raise ModelFilesMissing(
            missing=health.missing_files,
            invalid=health.invalid_files,
            message=health.summary(),
        )
    return health
