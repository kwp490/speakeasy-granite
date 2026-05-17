"""
Model downloader using huggingface_hub.

Downloads the IBM Granite Speech model from HuggingFace Hub to local storage.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal

log = logging.getLogger(__name__)

# ── Exit codes (also used by installer/speakeasy-setup.iss) ───────────────────
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_AUTH_REQUIRED = 2  # gated repo — anonymous access denied

PROGRESS_PREFIX = "SPEAKEASY_PROGRESS "
MODEL_DOWNLOAD_MIN_FREE_BYTES = 5 * 1024 * 1024 * 1024
MODEL_DOWNLOAD_MAX_ATTEMPTS = 3
ProgressFormat = Literal["text", "jsonl", "none"]

# ── Model constants (single source of truth) ─────────────────────────────────

GRANITE_REPO_ID = "ibm-granite/granite-speech-4.1-2b"

GRANITE_REQUIRED_FILES = (
    "config.json",
    "processor_config.json",
    "preprocessor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.json",
    "merges.txt",
    "added_tokens.json",
    "chat_template.jinja",
    "model.safetensors.index.json",
)

_ENGINE_REPO_MAP = {
    "granite": GRANITE_REPO_ID,
}

_MODEL_REQUIRED_FILES = {
    "granite": GRANITE_REQUIRED_FILES,
}


@dataclass(frozen=True)
class DownloadProgress:
    """Progress event emitted while preparing or downloading a model."""

    phase: str
    message: str
    percent: int | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    label: str | None = None


@dataclass(frozen=True)
class ModelHealth:
    """Lightweight on-disk health report for a downloaded model."""

    engine_name: str
    model_path: str
    engine_dir: str
    missing_files: tuple[str, ...] = ()
    invalid_files: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.missing_files and not self.invalid_files

    def summary(self) -> str:
        if self.ready:
            return f"{self.engine_name.capitalize()} model is ready."
        parts: list[str] = []
        if self.missing_files:
            parts.append("missing " + ", ".join(self.missing_files))
        if self.invalid_files:
            parts.append("invalid " + ", ".join(self.invalid_files))
        return f"{self.engine_name.capitalize()} model is incomplete: " + "; ".join(parts)


ProgressCallback = Callable[[DownloadProgress], None]


def _compact_progress_dict(progress: DownloadProgress) -> dict[str, object]:
    """Return a JSON-friendly progress dict without null fields."""
    return {key: value for key, value in asdict(progress).items() if value is not None}


def _format_bytes(num_bytes: int) -> str:
    """Format byte counts for user-facing progress messages."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _format_progress_text(progress: DownloadProgress) -> str:
    """Format a progress event for manual console use."""
    if progress.phase == "progress" and progress.percent is not None:
        details = f"{progress.percent}%"
        if progress.downloaded_bytes is not None and progress.total_bytes:
            details += (
                f" ({_format_bytes(progress.downloaded_bytes)} / "
                f"{_format_bytes(progress.total_bytes)})"
            )
        if progress.label:
            return f"{progress.message}: {details} - {progress.label}"
        return f"{progress.message}: {details}"
    return progress.message


def _check_disk_space(target_dir: str) -> tuple[bool, int | None, int]:
    """Return whether *target_dir* has enough free space for model download."""
    try:
        usage = shutil.disk_usage(target_dir)
    except OSError:
        return True, None, MODEL_DOWNLOAD_MIN_FREE_BYTES
    return usage.free >= MODEL_DOWNLOAD_MIN_FREE_BYTES, usage.free, MODEL_DOWNLOAD_MIN_FREE_BYTES


def _file_is_nonempty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _json_file_is_valid(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as handle:
            json.load(handle)
        return True
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False


def _safe_index_reference(name: str) -> bool:
    ref_path = Path(name)
    return not ref_path.is_absolute() and ".." not in ref_path.parts


def model_health(engine_name: str, model_path: str) -> ModelHealth:
    """Return a lightweight health report for local model artifacts."""
    engine_dir = Path(model_path) / engine_name
    required_files = _MODEL_REQUIRED_FILES.get(engine_name)
    if required_files is None:
        return ModelHealth(
            engine_name=engine_name,
            model_path=model_path,
            engine_dir=str(engine_dir),
            invalid_files=(f"unsupported engine '{engine_name}'",),
        )

    if not engine_dir.is_dir():
        return ModelHealth(
            engine_name=engine_name,
            model_path=model_path,
            engine_dir=str(engine_dir),
            missing_files=(f"{engine_name}/",),
        )

    missing: set[str] = set()
    invalid: set[str] = set()
    for filename in required_files:
        file_path = engine_dir / filename
        if not file_path.is_file():
            missing.add(filename)
        elif not _file_is_nonempty(file_path):
            invalid.add(filename)
        elif filename.endswith(".json") and not _json_file_is_valid(file_path):
            invalid.add(filename)

    index_path = engine_dir / "model.safetensors.index.json"
    if index_path.is_file() and "model.safetensors.index.json" not in invalid:
        try:
            with index_path.open("r", encoding="utf-8") as handle:
                index_payload = json.load(handle)
            weight_map = index_payload.get("weight_map")
            if not isinstance(weight_map, dict) or not weight_map:
                invalid.add("model.safetensors.index.json")
            else:
                for shard_name in sorted(set(str(name) for name in weight_map.values())):
                    if not _safe_index_reference(shard_name):
                        invalid.add("model.safetensors.index.json")
                        continue
                    shard_path = engine_dir / shard_name
                    if not shard_path.is_file():
                        missing.add(shard_name)
                    elif not _file_is_nonempty(shard_path):
                        invalid.add(shard_name)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            invalid.add("model.safetensors.index.json")

    return ModelHealth(
        engine_name=engine_name,
        model_path=model_path,
        engine_dir=str(engine_dir),
        missing_files=tuple(sorted(missing)),
        invalid_files=tuple(sorted(invalid)),
    )


def _remove_invalid_model_files(health: ModelHealth) -> None:
    """Remove damaged required files so snapshot_download can replace them."""
    engine_dir = Path(health.engine_dir)
    for filename in health.invalid_files:
        if filename.startswith("unsupported engine") or not _safe_index_reference(filename):
            continue
        try:
            path = engine_dir / filename
            if path.is_file():
                path.unlink()
        except OSError:
            log.warning("Could not remove invalid model file: %s", filename, exc_info=True)


def _model_dir_has_files(path: str) -> bool:
    try:
        return any(Path(path).iterdir())
    except OSError:
        return False


class _ProgressReporter:
    """Fan out progress events to callbacks and optional stdout formats."""

    def __init__(
        self,
        callback: ProgressCallback | None,
        progress_format: ProgressFormat,
        progress_file: str | os.PathLike[str] | None = None,
    ) -> None:
        self._callback = callback
        self._format = progress_format
        self._progress_file = Path(progress_file) if progress_file else None
        self._last_key: tuple[str, int | None, str | None] | None = None
        self._last_emit = 0.0

        if self._progress_file is not None:
            self._progress_file.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, progress: DownloadProgress, *, force: bool = False) -> None:
        if self._callback is not None:
            self._callback(progress)

        if progress.phase == "progress" and not force:
            key = (progress.phase, progress.percent, progress.label)
            now = time.monotonic()
            if key == self._last_key or now - self._last_emit < 0.5:
                return
            self._last_key = key
            self._last_emit = now

        jsonl_line = None
        if self._format == "jsonl" or self._progress_file is not None:
            payload = json.dumps(_compact_progress_dict(progress), ensure_ascii=True)
            jsonl_line = f"{PROGRESS_PREFIX}{payload}"

        if self._progress_file is not None and jsonl_line is not None:
            with self._progress_file.open("a", encoding="utf-8") as handle:
                handle.write(jsonl_line + "\n")

        if self._format == "none":
            return

        if self._format == "jsonl":
            print(jsonl_line, flush=True)
        else:
            print(_format_progress_text(progress), flush=True)


def _build_progress_tqdm_class(reporter: _ProgressReporter):
    """Return a HuggingFace tqdm subclass that emits structured progress."""
    from huggingface_hub.utils.tqdm import tqdm as hf_tqdm

    class SpeakEasyProgressTqdm(hf_tqdm):
        def __init__(self, *args, **kwargs):
            kwargs["disable"] = True
            super().__init__(*args, **kwargs)
            self._speakeasy_last_percent: int | None = None
            self._speakeasy_last_emit = 0.0
            self._speakeasy_emit(force=True)

        def update(self, n=1):
            result = super().update(n)
            self._speakeasy_emit()
            return result

        def close(self):
            self._speakeasy_emit(force=True)
            return super().close()

        def _speakeasy_emit(self, *, force: bool = False) -> None:
            total = int(self.total) if self.total else None
            current = int(self.n) if self.n is not None else 0
            percent = None
            if total and total > 0:
                percent = max(0, min(100, int(current * 100 / total)))

            now = time.monotonic()
            if not force:
                if percent is not None and percent == self._speakeasy_last_percent:
                    return
                if now - self._speakeasy_last_emit < 0.5:
                    return

            self._speakeasy_last_percent = percent
            self._speakeasy_last_emit = now

            unit = getattr(self, "unit", None)
            downloaded_bytes = current if unit == "B" else None
            total_bytes = total if unit == "B" else None
            label = str(getattr(self, "desc", "") or "").strip() or None

            reporter.emit(
                DownloadProgress(
                    phase="progress",
                    message="Downloading model files",
                    percent=percent,
                    downloaded_bytes=downloaded_bytes,
                    total_bytes=total_bytes,
                    label=label,
                ),
                force=force,
            )

    return SpeakEasyProgressTqdm


def get_granite_setup_script_candidates() -> tuple[Path, Path]:
    """Return the install and source locations for the setup script."""
    from speakeasy.config import INSTALL_DIR

    repo_root = Path(__file__).resolve().parent.parent
    return (
        INSTALL_DIR / "granite-model-setup.ps1",
        repo_root / "installer" / "granite-model-setup.ps1",
    )


def find_granite_setup_script() -> Path | None:
    """Return the first available Granite setup script path."""
    for script in get_granite_setup_script_candidates():
        if script.is_file():
            return script
    return None


def launch_granite_setup_script(
    target_dir: str | None = None,
    *,
    require_elevation: bool = False,
) -> int:
    """Launch the installed Granite setup script via PowerShell.

    Returns the ``ShellExecuteW`` result code. Values greater than 32
    indicate the script was launched successfully.
    """
    script = find_granite_setup_script()
    if script is None:
        raise FileNotFoundError("granite-model-setup.ps1 was not found")

    @dataclass(frozen=True)
    class ModelHealth:
        """Lightweight on-disk health report for a downloaded model."""

        engine_name: str
        model_path: str
        engine_dir: str
        missing_files: tuple[str, ...] = ()
        invalid_files: tuple[str, ...] = ()

        @property
        def ready(self) -> bool:
            return not self.missing_files and not self.invalid_files

        def summary(self) -> str:
            if self.ready:
                return f"{self.engine_name.capitalize()} model is ready."
            parts: list[str] = []
            if self.missing_files:
                parts.append("missing " + ", ".join(self.missing_files))
            if self.invalid_files:
                parts.append("invalid " + ", ".join(self.invalid_files))
            return f"{self.engine_name.capitalize()} model is incomplete: " + "; ".join(parts)
    verb = "runas" if require_elevation else "open"
    args = f'-NoProfile -ExecutionPolicy Bypass -File "{script}"'
    if target_dir:
        args += f' -TargetDir "{target_dir}"'

    return int(
        ctypes.windll.shell32.ShellExecuteW(
            None,
            verb,
            "powershell.exe",
            args,
            str(script.parent),
            1,
        )
    )


def _is_gated_repo_error(exc: Exception) -> bool:
    """Return True if *exc* indicates a gated/restricted HuggingFace repo."""
    try:
        from huggingface_hub.errors import GatedRepoError
        if isinstance(exc, GatedRepoError):
            return True
    except ImportError:
        pass
    msg = str(exc)
    return ("gated repo" in msg.lower()
            or "access to model" in msg.lower()
            or ("401" in msg and "restricted" in msg.lower()))


def _run_download_preflight(
    engine_name: str,
    target_dir: str,
    reporter: _ProgressReporter,
) -> int:
    """Validate the frozen download path without downloading model files."""
    has_space, free_bytes, required_bytes = _check_disk_space(target_dir)
    if free_bytes is None:
        reporter.emit(
            DownloadProgress(
                phase="preflight",
                message=(
                    "Could not verify free disk space for the model download; "
                    "continuing check-only validation."
                ),
            ),
            force=True,
        )
    elif not has_space:
        reporter.emit(
            DownloadProgress(
                phase="error",
                message=(
                    "ERROR: Not enough free disk space for the Granite model download. "
                    f"Available: {_format_bytes(free_bytes)}; "
                    f"required: {_format_bytes(required_bytes)}."
                ),
            ),
            force=True,
        )
        return EXIT_FAILURE
    else:
        reporter.emit(
            DownloadProgress(
                phase="preflight",
                message=(
                    "Disk space check passed: "
                    f"{_format_bytes(free_bytes)} available, "
                    f"{_format_bytes(required_bytes)} required."
                ),
            ),
            force=True,
        )

    try:
        import certifi
        import huggingface_hub  # noqa: F401

        ca_bundle = certifi.where()
        if not os.path.isfile(ca_bundle):
            raise FileNotFoundError(f"certifi CA bundle not found: {ca_bundle}")

        marker_path = os.path.join(target_dir, ".speakeasy-download-check.tmp")
        with open(marker_path, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(marker_path)
    except Exception as exc:
        log.exception("Model download preflight failed")
        reporter.emit(
            DownloadProgress(
                phase="error",
                message=f"ERROR: Download preflight failed: {exc}",
            ),
            force=True,
        )
        return EXIT_FAILURE

    reporter.emit(
        DownloadProgress(
            phase="complete",
            message=f"{engine_name.capitalize()} model download preflight passed.",
            percent=100,
        ),
        force=True,
    )
    return EXIT_SUCCESS


def download_model(
    engine_name: str,
    model_path: str,
    token: str | None = None,
    *,
    progress_callback: ProgressCallback | None = None,
    progress_format: ProgressFormat = "text",
    progress_file: str | os.PathLike[str] | None = None,
    check_only: bool = False,
) -> int:
    """Download model files for *engine_name* to *model_path*/<engine_name>.

    Returns
    -------
    EXIT_SUCCESS (0)
        Download succeeded or model already present.
    EXIT_FAILURE (1)
        Unexpected error (network, disk, etc.).
    EXIT_AUTH_REQUIRED (2)
        Repository is gated — anonymous download not possible.
    """
    if progress_format not in ("text", "jsonl", "none"):
        raise ValueError("progress_format must be 'text', 'jsonl', or 'none'")

    reporter = _ProgressReporter(progress_callback, progress_format, progress_file)
    repo_id = _ENGINE_REPO_MAP.get(engine_name)
    if repo_id is None:
        reporter.emit(
            DownloadProgress(
                phase="error",
                message=(
                    f"ERROR: Unknown engine '{engine_name}'. "
                    f"Choose from: {list(_ENGINE_REPO_MAP)}"
                ),
            ),
            force=True,
        )
        return EXIT_FAILURE

    target_dir = os.path.join(model_path, engine_name)
    os.makedirs(target_dir, exist_ok=True)

    reporter.emit(
        DownloadProgress(
            phase="checking",
            message=f"Checking for existing {engine_name} model in {target_dir}",
        ),
        force=True,
    )

    if check_only:
        return _run_download_preflight(engine_name, target_dir, reporter)

    health = model_health(engine_name, model_path)
    if health.ready:
        reporter.emit(
            DownloadProgress(
                phase="already_present",
                message=(
                    f"{engine_name.capitalize()} model already present in "
                    f"{target_dir} - skipping download."
                ),
                percent=100,
            ),
            force=True,
        )
        return EXIT_SUCCESS

    if (health.missing_files or health.invalid_files) and _model_dir_has_files(target_dir):
        reporter.emit(
            DownloadProgress(
                phase="repairing",
                message=health.summary() + "; repairing from HuggingFace.",
            ),
            force=True,
        )
        _remove_invalid_model_files(health)

    has_space, free_bytes, required_bytes = _check_disk_space(target_dir)
    if free_bytes is None:
        reporter.emit(
            DownloadProgress(
                phase="preflight",
                message=(
                    "Could not verify free disk space for the model download; "
                    "continuing anyway."
                ),
            ),
            force=True,
        )
    else:
        reporter.emit(
            DownloadProgress(
                phase="preflight",
                message=(
                    "Disk space check passed: "
                    f"{_format_bytes(free_bytes)} available, "
                    f"{_format_bytes(required_bytes)} required."
                ),
            ),
            force=True,
        )

    if not has_space:
        reporter.emit(
            DownloadProgress(
                phase="error",
                message=(
                    "ERROR: Not enough free disk space for the Granite model download. "
                    f"Available: {_format_bytes(free_bytes or 0)}; "
                    f"required: {_format_bytes(required_bytes)}."
                ),
            ),
            force=True,
        )
        return EXIT_FAILURE

    try:
        import huggingface_hub
    except ImportError:
        log.exception("huggingface_hub import failed during model download")
        reporter.emit(
            DownloadProgress(
                phase="error",
                message=(
                    "ERROR: huggingface-hub is required for model downloads. "
                    "Install it with the project dependencies."
                ),
            ),
            force=True,
        )
        return EXIT_FAILURE

    reporter.emit(
        DownloadProgress(
            phase="downloading",
            message=f"Downloading {engine_name} model from {repo_id} to {target_dir}",
            percent=0,
        ),
        force=True,
    )
    try:
        snapshot_kwargs = {
            "repo_id": repo_id,
            "local_dir": target_dir,
            "local_files_only": False,
            "token": token,
        }
        try:
            snapshot_kwargs["tqdm_class"] = _build_progress_tqdm_class(reporter)
        except (ImportError, AttributeError):
            pass

        for attempt in range(1, MODEL_DOWNLOAD_MAX_ATTEMPTS + 1):
            try:
                try:
                    huggingface_hub.snapshot_download(**snapshot_kwargs)
                except TypeError as exc:
                    if "tqdm_class" not in str(exc):
                        raise
                    snapshot_kwargs.pop("tqdm_class", None)
                    huggingface_hub.snapshot_download(**snapshot_kwargs)
                break
            except Exception as exc:
                if _is_gated_repo_error(exc) or attempt >= MODEL_DOWNLOAD_MAX_ATTEMPTS:
                    raise
                log.warning(
                    "Model download attempt %s of %s failed; retrying",
                    attempt,
                    MODEL_DOWNLOAD_MAX_ATTEMPTS,
                    exc_info=True,
                )
                reporter.emit(
                    DownloadProgress(
                        phase="retrying",
                        message=(
                            "Download attempt "
                            f"{attempt} of {MODEL_DOWNLOAD_MAX_ATTEMPTS} failed: {exc}. "
                            f"Retrying attempt {attempt + 1}."
                        ),
                    ),
                    force=True,
                )
                time.sleep(min(2 ** (attempt - 1), 8))

        reporter.emit(
            DownloadProgress(
                phase="verifying",
                message=f"Verifying {engine_name} model files",
            ),
            force=True,
        )
        # Verify the download actually produced usable model files
        health = model_health(engine_name, model_path)
        if not health.ready:
            log.error("Model verification failed after download: %s", target_dir)
            reporter.emit(
                DownloadProgress(
                    phase="error",
                    message=(
                        "ERROR: Download appeared to succeed but model files are "
                        f"incomplete in {target_dir}. {health.summary()}"
                    ),
                ),
                force=True,
            )
            return EXIT_FAILURE
        reporter.emit(
            DownloadProgress(
                phase="complete",
                message=f"{engine_name.capitalize()} model download complete.",
                percent=100,
            ),
            force=True,
        )
        return EXIT_SUCCESS
    except Exception as exc:
        if _is_gated_repo_error(exc):
            log.exception("Model download requires HuggingFace authorization")
            if token:
                message = (
                    f"AUTH REQUIRED: token was provided but access was still denied for {repo_id}.\n"
                    f"Detail: {exc}\n"
                    f"Possible causes:\n"
                    f"  - The token belongs to a different HuggingFace account than the one\n"
                    f"    that accepted the license at:\n"
                    f"    https://huggingface.co/{repo_id}\n"
                    f"  - The token has expired or was revoked\n"
                    f"  - HuggingFace is temporarily unavailable"
                )
            else:
                message = (
                    f"AUTH REQUIRED: {repo_id} is a gated model. "
                    f"A HuggingFace access token is required.\n"
                    f"Detail: {exc}"
                )
            reporter.emit(
                DownloadProgress(phase="auth_required", message=message),
                force=True,
            )
            return EXIT_AUTH_REQUIRED
        log.exception("Model download failed")
        msg = str(exc)
        if "401" in msg or "Repository Not Found" in msg:
            message = f"ERROR: Repo not found or access denied: {exc}"
        else:
            message = f"ERROR: Download failed: {exc}"
        reporter.emit(
            DownloadProgress(phase="error", message=message),
            force=True,
        )
        return EXIT_FAILURE


def model_ready(engine_name: str, model_path: str) -> bool:
    """Return True if the model files for *engine_name* pass health checks."""
    return model_health(engine_name, model_path).ready
