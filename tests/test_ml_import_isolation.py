"""Phase 2 import-isolation guarantee (P0).

The UI process must not import torch/transformers/librosa/accelerate at module
scope.  These tests spawn a fresh interpreter with a ``sys.meta_path`` blocker
that raises on importing any of those packages, then import the UI / contract /
services / registry modules and assert success.

The blocker is modelled on
``tests/test_contract.py::test_core_imports_without_ml_packages`` but does *not*
block PySide6 — the UI legitimately imports Qt at module scope; only the heavy
ML packages must stay behind the engine boundary.
"""

import subprocess
import sys


# Heavy ML packages that must never be imported at UI module scope.
_BLOCKED = ("torch", "transformers", "librosa", "accelerate")


def _run_isolated_import(import_lines: str) -> subprocess.CompletedProcess:
    """Run *import_lines* in a subprocess with the ML packages blocked."""
    prelude = (
        "import importlib.abc\n"
        "import importlib.machinery\n"
        "import sys\n"
        f"BLOCKED = {_BLOCKED!r}\n"
        "class _MLBlocker(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path, target=None):\n"
        "        if name.split('.')[0] in BLOCKED:\n"
        "            raise ImportError('blocked by import-isolation test: ' + name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, _MLBlocker())\n"
    )
    postlude = (
        # Belt-and-suspenders: nothing imported above may have pulled a blocked
        # package in transitively.
        "leaked = sorted(m for m in BLOCKED if m in sys.modules)\n"
        "assert not leaked, 'blocked packages were imported: ' + repr(leaked)\n"
        "print('ok')\n"
    )
    if not import_lines.endswith("\n"):
        import_lines += "\n"
    program = prelude + import_lines + postlude
    return subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
    )


def test_main_window_imports_without_ml_packages():
    """`import speakeasy.main_window` must succeed with torch/etc. blocked."""
    proc = _run_isolated_import("import speakeasy.main_window")
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_contract_and_services_import_without_ml_packages():
    """The contract, services and registry must import torch-free."""
    proc = _run_isolated_import(
        "import speakeasy.core.contract\n"
        "import speakeasy.services\n"
        "import speakeasy.services.inprocess\n"
        "import speakeasy.engines.registry\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_engine_package_imports_without_ml_packages():
    """Importing the legacy engine package (and submodules) stays torch-free."""
    proc = _run_isolated_import(
        "import speakeasy.engine\n"
        "import speakeasy.engine.base\n"
        "import speakeasy.engine.audio_utils\n"
        "import speakeasy.engine.granite_transcribe\n"
        "assert isinstance(speakeasy.engine.ENGINES, dict)\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_installed_engines_is_torch_free():
    """`installed_engines()` must answer via find_spec without importing torch."""
    proc = _run_isolated_import(
        "from speakeasy.engines.registry import installed_engines\n"
        "installed_engines()\n"  # must not raise even though torch is blocked
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_ensure_16khz_functions_with_librosa_blocked():
    """The real proof librosa is off the hot path: resampling still works.

    With librosa blocked at import time, ``ensure_16khz`` must still resample
    (soxr handles it).  This asserts functionality, not just that the module
    imports — it is what makes the Phase 2.5 swap safe.
    """
    proc = _run_isolated_import(
        "import numpy as np\n"
        "from speakeasy.core.resample import ensure_16khz as core_ensure\n"
        "from speakeasy.engine.audio_utils import ensure_16khz as engine_ensure\n"
        "audio = np.sin(np.linspace(0, 100, 48000)).astype(np.float32)\n"
        "out = core_ensure(audio, 48000)\n"
        "assert out.dtype == np.float32, out.dtype\n"
        "assert len(out) == 16000, len(out)\n"
        # engine path must delegate to the same soxr-backed implementation
        "assert engine_ensure is core_ensure\n"
        "out2 = engine_ensure(audio, 48000)\n"
        "assert len(out2) == 16000, len(out2)\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout

