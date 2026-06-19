"""Frozen-build ML-isolation invariants (Phase 2 split out of test_frozen_compat).

Two complementary guarantees live here:

* **Inverse module-scope assertions** — torch/transformers/librosa/accelerate
  must NOT be imported at module scope by the UI (`main_window`) or the
  `core`/`services` layers, and the Granite engine must import them only inside
  function bodies.  These are the static counterpart to the subprocess test in
  ``test_ml_import_isolation.py``.
* **Packaging coupling** — because the heavy imports are now *lazy*, PyInstaller
  can no longer discover them by static analysis, so the ``hiddenimports`` in
  ``speakeasy.spec`` must still list them.  Those assertions (moved unchanged
  from ``test_frozen_compat.py``) stay green this phase; the hiddenimports
  cleanup is a later phase.
"""

import ast
import re
import sys
import unittest
from pathlib import Path

_SPEAKEASY_PKG = Path(__file__).resolve().parent.parent / "speakeasy"
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Shared PyInstaller build logic moved to spec_common.py (Phase 7); the specs
# are thin shims, so packaging-coupling assertions consult spec_common.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import spec_common  # noqa: E402

_SPEC_COMMON_SRC = (_REPO_ROOT / "spec_common.py").read_text(encoding="utf-8")

# Heavy ML packages that must stay behind the engine boundary.
_BLOCKED = frozenset({"torch", "transformers", "librosa", "accelerate"})


def _imports_by_scope(path: Path) -> tuple[set[str], set[str]]:
    """Return ``(module_scope_tops, function_scope_tops)`` for *path*.

    ``module_scope_tops`` are top-level module names imported at import time
    (module body, including class bodies and module-level ``try``/``if``).
    ``function_scope_tops`` are imported only inside function/method bodies.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
    module_scope: set[str] = set()
    function_scope: set[str] = set()

    def _collect(node: ast.AST) -> None:
        for alias in getattr(node, "names", []):
            module_scope.add(alias.name.split(".")[0])

    def _walk_module(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _walk_function(child)
            elif isinstance(child, ast.Import):
                _collect(child)
            elif isinstance(child, ast.ImportFrom):
                if child.module:
                    module_scope.add(child.module.split(".")[0])
            else:
                _walk_module(child)

    def _walk_function(node: ast.AST) -> None:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                for alias in sub.names:
                    function_scope.add(alias.name.split(".")[0])
            elif isinstance(sub, ast.ImportFrom) and sub.module:
                function_scope.add(sub.module.split(".")[0])

    _walk_module(tree)
    return module_scope, function_scope


class TestModuleScopeMLIsolation(unittest.TestCase):
    """The inverse of the old coupling: no module-scope ML imports in the UI."""

    _UI_AND_CORE = (
        "main_window.py",
        "core/contract.py",
        "core/errors.py",
        "core/model_source.py",
        "core/resample.py",
        "core/wire.py",
        "services/inprocess.py",
        "services/provisioning.py",
        "services/remote_client.py",
        "services/server.py",
        "engines/registry.py",
    )

    def test_ui_and_core_have_no_module_scope_ml_imports(self):
        offenders = []
        for rel in self._UI_AND_CORE:
            module_scope, _ = _imports_by_scope(_SPEAKEASY_PKG / rel)
            leaked = sorted(_BLOCKED & module_scope)
            if leaked:
                offenders.append(f"{rel}: {leaked}")
        self.assertEqual(
            offenders,
            [],
            "Heavy ML packages must not be imported at module scope:\n"
            + "\n".join(offenders),
        )

    def test_granite_engine_imports_torch_lazily(self):
        """Granite must still use torch/transformers — but only inside functions."""
        module_scope, function_scope = _imports_by_scope(
            _SPEAKEASY_PKG / "engine" / "granite_transcribe.py"
        )
        self.assertNotIn("torch", module_scope, "torch must be a lazy import")
        self.assertNotIn(
            "transformers", module_scope, "transformers must be a lazy import"
        )
        self.assertIn(
            "torch", function_scope, "torch must still be imported inside load()/methods"
        )
        self.assertIn(
            "transformers",
            function_scope,
            "transformers must still be imported inside load()/methods",
        )

    def test_engine_init_is_torch_free(self):
        """The legacy engine package must not import torch/transformers at all."""
        module_scope, function_scope = _imports_by_scope(
            _SPEAKEASY_PKG / "engine" / "__init__.py"
        )
        self.assertEqual(
            _BLOCKED & (module_scope | function_scope),
            set(),
            "speakeasy.engine.__init__ must not import any ML package",
        )


class TestTransitiveDependenciesInSpec(unittest.TestCase):
    """Lazy imports still need explicit hiddenimports until the Phase 7 cleanup.

    Moved unchanged from ``test_frozen_compat.py``: the ``.spec`` hiddenimports
    are deliberately left as-is this phase so PyInstaller keeps bundling the
    now-lazy torch/transformers stack.  Phase 2.5 swapped the resampler from
    librosa to soxr, so soxr is now asserted present and librosa absent.
    """

    def _read_spec(self) -> str:
        # Build logic now lives in spec_common.py (specs are thin shims).
        return _SPEC_COMMON_SRC

    def _parse_hidden_imports(self) -> set[str]:
        # GPU variant carries the full hiddenimports superset.
        return set(spec_common.hidden_imports("gpu"))

    def _parse_excludes(self) -> set[str]:
        return set(spec_common.excludes_for("gpu"))

    def test_transformers_in_hiddenimports(self):
        hidden = self._parse_hidden_imports()
        self.assertIn("transformers", hidden)

    def test_torch_in_hiddenimports(self):
        hidden = self._parse_hidden_imports()
        self.assertIn("torch", hidden)

    def test_soxr_in_hiddenimports(self):
        """soxr backs the shared 16 kHz resampling path and is imported lazily.

        Phase 2.5 replaced librosa with soxr in ``core/resample.py``.  Because
        the import is lazy (inside ``_resample``), PyInstaller cannot discover
        it by static analysis, so soxr must be listed explicitly or the frozen
        build fails at the first resample (R-2).
        """
        hidden = self._parse_hidden_imports()
        self.assertIn("soxr", hidden)

    def test_librosa_not_in_hiddenimports(self):
        """librosa was dropped in Phase 2.5; it is no longer an app dependency.

        soxr is the single resampling implementation, so librosa must not be
        bundled (it pulled in the numba/llvmlite/scipy chain).  Keeping it in
        hiddenimports would also break the frozen build now that librosa is no
        longer installed.
        """
        hidden = self._parse_hidden_imports()
        self.assertNotIn("librosa", hidden)

    def test_transformers_model_sources_collected(self):
        """Frozen builds must ship the root transformers entrypoint and models source tree used by lazy imports."""
        spec = self._read_spec()
        self.assertIn("('transformers', {'include_py_files': True, 'includes': ['__init__.py']})", spec)
        self.assertIn("('transformers.models', {'include_py_files': True})", spec)
        self.assertIn("include_py_files': True", spec)

    def test_safetensors_in_hiddenimports(self):
        """safetensors is used by Transformers model weight loading."""
        hidden = self._parse_hidden_imports()
        self.assertIn("safetensors", hidden)

    def test_transformers_data_files_collected(self):
        spec_text = self._read_spec()
        self.assertIn(
            "collect_data_files(",
            spec_text,
            "speakeasy.spec must call collect_data_files() for transformers data",
        )
        self.assertIn(
            "transformers",
            spec_text,
            "speakeasy.spec must reference transformers in data file collection",
        )

    def test_sklearn_excluded(self):
        """sklearn should be excluded from the frozen bundle."""
        excludes = self._parse_excludes()
        self.assertIn("sklearn", excludes)


if __name__ == "__main__":
    unittest.main()
