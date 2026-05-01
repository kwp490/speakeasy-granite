"""
Model downloader using huggingface_hub.

Downloads the IBM Granite Speech model from HuggingFace Hub to local storage.
"""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# ── Exit codes (also used by installer/speakeasy-setup.iss) ───────────────────
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_AUTH_REQUIRED = 2  # gated repo — anonymous access denied

# ── Model constants (single source of truth) ─────────────────────────────────

GRANITE_REPO_ID = "ibm-granite/granite-speech-4.1-2b"

_ENGINE_REPO_MAP = {
    "granite": GRANITE_REPO_ID,
}


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


def download_model(engine_name: str, model_path: str, token: str | None = None) -> int:
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
    repo_id = _ENGINE_REPO_MAP.get(engine_name)
    if repo_id is None:
        print(f"ERROR: Unknown engine '{engine_name}'. Choose from: {list(_ENGINE_REPO_MAP)}")
        return EXIT_FAILURE

    target_dir = os.path.join(model_path, engine_name)
    os.makedirs(target_dir, exist_ok=True)

    # Check if already downloaded
    if model_ready(engine_name, model_path):
        print(f"{engine_name.capitalize()} model already present in {target_dir} — skipping download.")
        return EXIT_SUCCESS

    try:
        import huggingface_hub
    except ImportError:
        print("ERROR: huggingface-hub is required for model downloads.")
        print("Install it: pip install huggingface-hub")
        return EXIT_FAILURE

    print(f"Downloading {engine_name} model from {repo_id} to {target_dir}...")
    try:
        huggingface_hub.snapshot_download(
            repo_id=repo_id,
            local_dir=target_dir,
            local_files_only=False,
            token=token,
        )
        # Verify the download actually produced usable model files
        if not model_ready(engine_name, model_path):
            print(f"ERROR: Download appeared to succeed but model files are incomplete in {target_dir}.")
            return EXIT_FAILURE
        print(f"{engine_name.capitalize()} model download complete.")
        return EXIT_SUCCESS
    except Exception as exc:
        if _is_gated_repo_error(exc):
            if token:
                print(
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
                print(
                    f"AUTH REQUIRED: {repo_id} is a gated model. "
                    f"A HuggingFace access token is required.\n"
                    f"Detail: {exc}"
                )
            return EXIT_AUTH_REQUIRED
        msg = str(exc)
        if "401" in msg or "Repository Not Found" in msg:
            print(f"ERROR: Repo not found or access denied: {exc}")
        else:
            print(f"ERROR: Download failed: {exc}")
        return EXIT_FAILURE


def model_ready(engine_name: str, model_path: str) -> bool:
    """Return True if the model files for *engine_name* exist."""
    engine_dir = os.path.join(model_path, engine_name)
    return os.path.isdir(engine_dir) and os.path.isfile(
        os.path.join(engine_dir, "config.json")
    )
