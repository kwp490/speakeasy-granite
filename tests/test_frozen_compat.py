"""Tests for PyInstaller frozen-build compatibility.

These tests catch issues that only manifest in --noconsole PyInstaller builds:
- Relative imports in __main__.py (no parent package context)
- APIs that assume real file descriptors (faulthandler, fileno)
- Modules that must be importable via absolute paths
- Dynamic imports must be listed in speakeasy.spec hiddenimports
"""

import ast
import io
import os
import re
import sys
import unittest
from pathlib import Path

# Root of the speakeasy package
_SPEAKEASY_PKG = Path(__file__).resolve().parent.parent / "speakeasy"
_REPO_ROOT = Path(__file__).resolve().parent.parent


class TestNoRelativeImportsInMain(unittest.TestCase):
    """__main__.py must use absolute imports for PyInstaller compatibility."""

    def test_no_relative_imports(self):
        source = (_SPEAKEASY_PKG / "__main__.py").read_text(encoding="utf-8")
        tree = ast.parse(source, filename="__main__.py")

        relative_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level and node.level > 0:
                relative_imports.append(
                    f"line {node.lineno}: from {'.' * node.level}{node.module or ''} import ..."
                )

        self.assertEqual(
            relative_imports,
            [],
            f"__main__.py must not use relative imports (breaks PyInstaller):\n"
            + "\n".join(relative_imports),
        )


class TestFaulthandlerWithStringIO(unittest.TestCase):
    """faulthandler.enable() must be guarded for --noconsole builds."""

    def test_faulthandler_tolerates_stringio_stderr(self):
        import faulthandler

        original_stderr = sys.stderr
        try:
            sys.stderr = io.StringIO()
            try:
                faulthandler.enable()
            except io.UnsupportedOperation:
                pass
        finally:
            sys.stderr = original_stderr

    def test_main_guards_faulthandler(self):
        source = (_SPEAKEASY_PKG / "__main__.py").read_text(encoding="utf-8")
        self.assertIn("io.UnsupportedOperation", source,
                       "faulthandler.enable() must be guarded with "
                       "except io.UnsupportedOperation")


class TestStdioSafetyPatches(unittest.TestCase):
    """__main__.py must patch None stdout/stderr for --noconsole builds."""

    def test_stdout_none_guard_exists(self):
        source = (_SPEAKEASY_PKG / "__main__.py").read_text(encoding="utf-8")
        self.assertIn("sys.stdout is None", source)

    def test_stderr_none_guard_exists(self):
        source = (_SPEAKEASY_PKG / "__main__.py").read_text(encoding="utf-8")
        self.assertIn("sys.stderr is None", source)

    def test_freeze_support_enabled(self):
        source = (_SPEAKEASY_PKG / "__main__.py").read_text(encoding="utf-8")
        self.assertIn(
            "multiprocessing.freeze_support()",
            source,
            "__main__.py must call multiprocessing.freeze_support() for Windows spawn/frozen workers",
        )

    def test_runtime_hook_exists(self):
        """A runtime hook must add _MEIPASS to DLL search paths before torch loads."""
        hook = _SPEAKEASY_PKG / "_runtime_hook_dll.py"
        self.assertTrue(hook.exists(), "speakeasy/_runtime_hook_dll.py is missing")
        source = hook.read_text(encoding="utf-8")
        self.assertIn("os.add_dll_directory", source)
        self.assertIn("_MEIPASS", source)
        self.assertIn('os.environ["PATH"]', source,
                       "Runtime hook must also prepend to PATH for legacy LoadLibraryW")

    def test_spec_uses_runtime_hook(self):
        """speakeasy.spec must reference the DLL runtime hook."""
        spec = (_REPO_ROOT / "speakeasy.spec").read_text(encoding="utf-8")
        self.assertIn("_runtime_hook_dll", spec,
                       "speakeasy.spec runtime_hooks must include _runtime_hook_dll")


class TestAllModulesImportable(unittest.TestCase):
    """Every .py file in speakeasy/ must be importable via absolute paths."""

    _SKIP_MODULES = frozenset()

    def test_import_all_modules(self):
        failures = []
        for py_file in sorted(_SPEAKEASY_PKG.rglob("*.py")):
            rel = py_file.relative_to(_SPEAKEASY_PKG.parent)
            module_name = str(rel.with_suffix("")).replace("\\", ".").replace("/", ".")

            if module_name in self._SKIP_MODULES:
                continue
            if "__pycache__" in module_name:
                continue

            try:
                __import__(module_name)
            except Exception as exc:
                failures.append(f"{module_name}: {type(exc).__name__}: {exc}")

        self.assertEqual(
            failures,
            [],
            f"Failed to import the following modules:\n" + "\n".join(failures),
        )


class TestRelativeImportsInSubpackages(unittest.TestCase):

    def test_engine_subpackage_imports(self):
        from speakeasy.engine import ENGINES
        self.assertIsInstance(ENGINES, dict)

    def test_engine_base_imports(self):
        from speakeasy.engine.base import SpeechEngine
        self.assertTrue(callable(SpeechEngine))


class TestHiddenImportsInSpec(unittest.TestCase):
    """Dynamic imports in __main__.py must be listed in speakeasy.spec hiddenimports."""

    _INTERNAL_PREFIXES = ("speakeasy.",)

    _STDLIB = frozenset({
        "argparse", "ctypes", "faulthandler", "io", "json", "logging",
        "logging.handlers", "os", "sys", "re", "pathlib", "tempfile",
        "time", "subprocess", "unittest", "importlib", "threading",
        "collections", "functools", "typing", "traceback", "copy",
        "shutil", "signal", "struct", "abc", "dataclasses", "enum",
    })

    def _parse_hidden_imports(self) -> set[str]:
        spec_path = _REPO_ROOT / "speakeasy.spec"
        spec_text = spec_path.read_text(encoding="utf-8")
        match = re.search(
            r"hiddenimports\s*=\s*\[(.*?)\]", spec_text, re.DOTALL
        )
        self.assertIsNotNone(match, "Could not find hiddenimports in speakeasy.spec")
        assert match is not None
        entries = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
        return set(entries)

    def _collect_deferred_imports(self, filepath: Path) -> list[tuple[int, str]]:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=filepath.name)

        deferred: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        deferred.append((child.lineno, alias.name.split(".")[0]))
                elif isinstance(child, ast.ImportFrom):
                    if child.level == 0 and child.module:
                        deferred.append((child.lineno, child.module.split(".")[0]))
        return deferred

    def test_dynamic_imports_in_hiddenimports(self):
        hidden = self._parse_hidden_imports()
        deferred = self._collect_deferred_imports(_SPEAKEASY_PKG / "__main__.py")

        missing = []
        for lineno, top_module in deferred:
            if top_module in self._STDLIB:
                continue
            if any(top_module.startswith(p.rstrip(".")) for p in self._INTERNAL_PREFIXES):
                continue
            if not any(h == top_module or h.startswith(top_module + ".") for h in hidden):
                missing.append(f"line {lineno}: {top_module}")

        self.assertEqual(
            missing,
            [],
            "Dynamic imports in __main__.py not listed in speakeasy.spec hiddenimports:\n"
            + "\n".join(missing)
            + "\nAdd them to hiddenimports in speakeasy.spec.",
        )

    def test_dynamic_imports_in_main_window(self):
        hidden = self._parse_hidden_imports()
        deferred = self._collect_deferred_imports(_SPEAKEASY_PKG / "main_window.py")

        missing = []
        for lineno, top_module in deferred:
            if top_module in self._STDLIB:
                continue
            if any(top_module.startswith(p.rstrip(".")) for p in self._INTERNAL_PREFIXES):
                continue
            if not any(h == top_module or h.startswith(top_module + ".") for h in hidden):
                missing.append(f"line {lineno}: {top_module}")

        self.assertEqual(
            missing,
            [],
            "Dynamic imports in main_window.py not listed in speakeasy.spec hiddenimports:\n"
            + "\n".join(missing)
            + "\nAdd them to hiddenimports in speakeasy.spec.",
        )


class TestTransitiveDependenciesInSpec(unittest.TestCase):
    """Transitive dependencies used at runtime must be bundled in the spec."""

    def _read_spec(self) -> str:
        return (_REPO_ROOT / "speakeasy.spec").read_text(encoding="utf-8")

    def _parse_hidden_imports(self) -> set[str]:
        spec_text = self._read_spec()
        match = re.search(
            r"hiddenimports\s*=\s*\[(.*?)\]", spec_text, re.DOTALL
        )
        assert match, "Could not find hiddenimports in speakeasy.spec"
        return set(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))

    def _parse_excludes(self) -> set[str]:
        spec_text = self._read_spec()
        match = re.search(
            r"excludes\s*=\s*\[(.*?)\]", spec_text, re.DOTALL
        )
        assert match, "Could not find excludes in speakeasy.spec"
        return set(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))

    def test_transformers_in_hiddenimports(self):
        hidden = self._parse_hidden_imports()
        self.assertIn("transformers", hidden)

    def test_torch_in_hiddenimports(self):
        hidden = self._parse_hidden_imports()
        self.assertIn("torch", hidden)

    def test_librosa_in_hiddenimports(self):
        """librosa is required by the shared 16 kHz resampling path."""
        hidden = self._parse_hidden_imports()
        self.assertIn("librosa", hidden)

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


class TestSpecStripPatterns(unittest.TestCase):
    """Verify stripped binaries are not needed and required ones are kept."""

    def _read_spec(self) -> str:
        return (_REPO_ROOT / "speakeasy.spec").read_text(encoding="utf-8")

    def _parse_strip_patterns(self) -> list[str]:
        spec_text = self._read_spec()
        return re.findall(r"_re\.compile\(r'([^']+)'", spec_text)

    # â”€â”€ Critical CUDA libs must NOT be stripped â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    _MUST_KEEP = [
        "cublas64", "cublasLt64", "cudart64", "cudnn64_9",
        "cudnn_graph64", "cudnn_ops64", "cudnn_cnn64",
        "cudnn_heuristic64", "cudnn_engines_precompiled64",
        "cudnn_engines_runtime_compiled64", "cudnn_adv64",
        "cufft64", "cufftw64", "cusolver64", "cusolverMg64",
        "cusparse64", "nvrtc64", "nvrtc-builtins64",
        "nvJitLink", "cupti64", "nvToolsExt64", "caffe2_nvrtc",
        "torch_cuda", "torch_cpu", "c10_cuda", "c10.dll", "shm.dll",
    ]

    def test_critical_cuda_libs_not_stripped(self):
        """Strip patterns must not match any critical CUDA/cuDNN library."""
        patterns = [re.compile(p, re.I) for p in self._parse_strip_patterns()]
        for lib in self._MUST_KEEP:
            for pat in patterns:
                self.assertIsNone(
                    pat.search(lib),
                    f"Strip r'{pat.pattern}' would remove critical '{lib}'.",
                )

    def test_pyside_translations_are_stripped(self):
        """Qt translation payload should be excluded from the frozen build."""
        patterns = [re.compile(p, re.I) for p in self._parse_strip_patterns()]
        self.assertTrue(
            any(p.search(r"PySide6\translations\qtbase_en.qm") for p in patterns),
            "PySide6 translations should be stripped from the frozen build.",
        )

    def test_unused_qt_plugins_are_stripped(self):
        """Unused Qt plugins should be removed to keep the bundle small."""
        patterns = [re.compile(p, re.I) for p in self._parse_strip_patterns()]
        unused_plugins = [
            r"PySide6\plugins\platforminputcontexts\qtvirtualkeyboardplugin.dll",
            r"PySide6\plugins\networkinformation\qnetworklistmanager.dll",
            r"PySide6\plugins\imageformats\qpdf.dll",
            r"PySide6\plugins\imageformats\qicns.dll",
            r"PySide6\plugins\imageformats\qtga.dll",
            r"PySide6\plugins\imageformats\qtiff.dll",
            r"PySide6\plugins\imageformats\qwbmp.dll",
            r"PySide6\plugins\imageformats\qwebp.dll",
        ]
        for plugin in unused_plugins:
            self.assertTrue(
                any(p.search(plugin) for p in patterns),
                f"speakeasy.spec should strip '{plugin}'.",
            )

    def test_windows_platform_plugin_not_stripped(self):
        """The qwindows platform plugin is required for the Windows GUI."""
        patterns = [re.compile(p, re.I) for p in self._parse_strip_patterns()]
        for pat in patterns:
            self.assertIsNone(
                pat.search(r"PySide6\plugins\platforms\qwindows.dll"),
                f"Strip r'{pat.pattern}' would remove qwindows.dll.",
            )

    def test_datas_filtered_with_strip_patterns(self):
        """Spec should filter data payloads as well as binaries."""
        spec_text = self._read_spec()
        self.assertIn(
            "a.datas = _filter_entries(a.datas)",
            spec_text,
            "speakeasy.spec must filter data entries with the strip patterns.",
        )

    def test_sklearn_payload_is_stripped(self):
        """Leftover sklearn package/data entries should be stripped from the bundle."""
        patterns = [re.compile(p, re.I) for p in self._parse_strip_patterns()]
        sample_entries = [
            r"sklearn\datasets\images\china.jpg",
            r"scikit_learn-1.8.0.dist-info\METADATA",
        ]
        for entry in sample_entries:
            self.assertTrue(
                any(p.search(entry) for p in patterns),
                f"speakeasy.spec should strip '{entry}'.",
            )

    # â”€â”€ Excluded modules must not break engine imports â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _parse_excludes(self) -> set[str]:
        spec_text = self._read_spec()
        m = re.search(r"excludes\s*=\s*\[(.*?)\]", spec_text, re.DOTALL)
        assert m, "Could not find excludes in speakeasy.spec"
        return set(re.findall(r"['\"]([^'\"]+)['\"]", m.group(1)))

    _ENGINE_DEPS = [
        "transformers", "torch", "torchaudio", "numpy",
        "huggingface_hub", "sentencepiece", "tokenizers",
        "librosa", "scipy", "safetensors",
    ]

    def test_engine_deps_not_excluded(self):
        """Top-level engine dependencies must not appear in excludes."""
        excludes = self._parse_excludes()
        for dep in self._ENGINE_DEPS:
            self.assertNotIn(
                dep, excludes,
                f"'{dep}' is excluded but is a direct engine dependency.",
            )

    _REQUIRED_TORCH = [
        "torch.nn", "torch.cuda", "torch.autograd",
        "torch.backends", "torch.utils",
    ]

    def test_required_torch_submodules_not_excluded(self):
        """Torch submodules used during inference must not be excluded."""
        excludes = self._parse_excludes()
        for mod in self._REQUIRED_TORCH:
            self.assertNotIn(
                mod, excludes,
                f"'{mod}' is required for model inference.",
            )

    def test_excluded_torch_modules_not_imported_at_startup(self):
        """Excluded torch submodules must not be loaded when torch starts.

        If torch begins importing an excluded module unconditionally (as
        happened with torch._strobelight in torch 2.11), PyInstaller
        will produce a build that crashes immediately with
        ``ModuleNotFoundError``.  Move such modules from ``excludes``
        to ``hiddenimports``.
        """
        import torch  # noqa: F401 â€” ensures torch startup imports are loaded
        excludes = {e for e in self._parse_excludes() if e.startswith("torch.")}

        loaded_and_excluded = []
        for mod_name in sorted(sys.modules):
            for excl in excludes:
                if mod_name == excl or mod_name.startswith(excl + "."):
                    loaded_and_excluded.append((mod_name, excl))
                    break

        self.assertEqual(
            loaded_and_excluded,
            [],
            "These modules are in speakeasy.spec excludes but were imported "
            "during torch startup â€” they must be moved to hiddenimports:\n"
            + "\n".join(f"  {mod} (matched exclude '{excl}')"
                        for mod, excl in loaded_and_excluded),
        )

    _REQUIRED_TF = [
        "transformers.models", "transformers.modeling_utils",
        "transformers.configuration_utils", "transformers.generation",
        "transformers.tokenization_utils_base", "transformers.processing_utils",
        "transformers.integrations",
    ]

    def test_required_transformers_submodules_not_excluded(self):
        """Transformers submodules used by engines must not be excluded."""
        excludes = self._parse_excludes()
        for mod in self._REQUIRED_TF:
            self.assertNotIn(
                mod, excludes,
                f"'{mod}' is needed for model loading.",
            )

    def test_no_blanket_cudnn_strip(self):
        """Strip patterns must not use a blanket pattern matching core cuDNN."""
        for raw in self._parse_strip_patterns():
            pat = re.compile(raw, re.I)
            self.assertIsNone(
                pat.search("cudnn64_9.dll"),
                f"r'{raw}' matches core cudnn64_9.dll",
            )
            self.assertIsNone(
                pat.search("cudnn_graph64_9.dll"),
                f"r'{raw}' matches cudnn_graph64_9.dll",
            )


class TestGraniteEngineCompat(unittest.TestCase):
    """Granite engine must use the generic Transformers speech seq2seq API."""

    def test_granite_engine_uses_speech_seq2seq_auto_model(self):
        source = (_REPO_ROOT / "speakeasy" / "engine" / "granite_transcribe.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("AutoModelForSpeechSeq2Seq", source)
        self.assertIn("apply_chat_template", source)


class TestDistOutputEssentials(unittest.TestCase):
    """If dist/ exists, verify critical torch/CUDA DLLs are present."""

    _DIST = _REPO_ROOT / "dist" / "speakeasy" / "_internal"

    @unittest.skipUnless(
        (_REPO_ROOT / "dist" / "speakeasy" / "_internal").is_dir(),
        "No dist/ build present",
    )
    def test_critical_cuda_dlls_present(self):
        """Core CUDA DLLs required for GPU inference must be in the build."""
        for pat in [
            "cublas64_*.dll", "cublasLt64_*.dll", "cudart64_*.dll",
            "cudnn64_*.dll", "cudnn_graph64_*.dll", "cudnn_ops64_*.dll",
            "cudnn_cnn64_*.dll", "cudnn_heuristic64_*.dll",
            "cudnn_engines_precompiled64_*.dll",
        ]:
            self.assertTrue(
                list(self._DIST.rglob(pat)),
                f"Required '{pat}' missing from dist/ â€” strip too aggressive?",
            )

    @unittest.skipUnless(
        (_REPO_ROOT / "dist" / "speakeasy" / "_internal").is_dir(),
        "No dist/ build present",
    )
    def test_torch_cuda_support_dlls_present(self):
        """Torch-managed CUDA support DLLs must be preserved in the build."""
        for pat in [
            "cufft64_*.dll", "cufftw64_*.dll", "cusolver64_*.dll",
            "cusolverMg64_*.dll", "cusparse64_*.dll",
            "cudnn_engines_runtime_compiled64_*.dll", "cudnn_adv64_*.dll",
            "cupti64_*.dll", "nvJitLink*.dll", "nvToolsExt64_*.dll",
            "nvrtc64_*.dll", "nvrtc-builtins64_*.dll", "caffe2_nvrtc.dll",
        ]:
            self.assertTrue(
                list(self._DIST.rglob(pat)),
                f"Required '{pat}' missing from dist/ â€” torch DLL strip too aggressive?",
            )

    @unittest.skipUnless(
        (_REPO_ROOT / "dist" / "speakeasy" / "_internal").is_dir(),
        "No dist/ build present",
    )
    def test_torch_core_present(self):
        """Core torch DLLs must be present (including shm.dll for multiprocessing)."""
        for name in ["torch_cpu.dll", "torch_cuda.dll", "torch.dll", "shm.dll", "c10.dll"]:
            self.assertTrue(
                list(self._DIST.rglob(name)),
                f"Core '{name}' missing from dist/.",
            )


class TestCpuSpecStripPatterns(unittest.TestCase):
    """CPU spec must strip ALL CUDA/NVIDIA DLLs from torch/lib/.

    Torch's _load_dll_libraries() globs torch/lib/*.dll and loads every
    DLL it finds.  If any CUDA DLL survives the CPU strip pass, torch
    will attempt to load it, fail because its CUDA dependencies are gone,
    and crash with WinError 126.
    """

    _CPU_SPEC = _REPO_ROOT / "speakeasy-cpu.spec"

    def _parse_cpu_strip_patterns(self) -> list[re.Pattern]:
        spec_text = self._CPU_SPEC.read_text(encoding="utf-8")
        raw = re.findall(r"_re\.compile\(r'([^']+)'", spec_text)
        return [re.compile(p, re.I) for p in raw]

    # Every CUDA/NVIDIA DLL shipped in a GPU torch's lib/ directory.
    # These must ALL be caught by the CPU spec's strip patterns.
    _CUDA_DLLS = [
        r"torch\lib\c10_cuda.dll",
        r"torch\lib\torch_cuda.dll",
        r"torch\lib\caffe2_nvrtc.dll",
        r"torch\lib\cublas64_12.dll",
        r"torch\lib\cublasLt64_12.dll",
        r"torch\lib\cudart64_12.dll",
        r"torch\lib\cudnn64_9.dll",
        r"torch\lib\cudnn_adv64_9.dll",
        r"torch\lib\cudnn_cnn64_9.dll",
        r"torch\lib\cudnn_engines_precompiled64_9.dll",
        r"torch\lib\cudnn_engines_runtime_compiled64_9.dll",
        r"torch\lib\cudnn_graph64_9.dll",
        r"torch\lib\cudnn_heuristic64_9.dll",
        r"torch\lib\cudnn_ops64_9.dll",
        r"torch\lib\cufft64_11.dll",
        r"torch\lib\cufftw64_11.dll",
        r"torch\lib\cupti64_2025.1.1.dll",
        r"torch\lib\curand64_10.dll",
        r"torch\lib\cusolver64_11.dll",
        r"torch\lib\cusolverMg64_11.dll",
        r"torch\lib\cusparse64_12.dll",
        r"torch\lib\nvJitLink_120_0.dll",
        r"torch\lib\nvperf_host.dll",
        r"torch\lib\nvToolsExt64_1.dll",
        r"torch\lib\nvrtc-builtins64_128.dll",
        r"torch\lib\nvrtc64_120_0.dll",
        r"torch\lib\nvrtc64_120_0.alt.dll",
    ]

    # DLLs that must NOT be stripped â€” the CPU build still needs these.
    _CPU_KEEP = [
        r"torch\lib\torch_cpu.dll",
        r"torch\lib\torch.dll",
        r"torch\lib\c10.dll",
        r"torch\lib\shm.dll",
        r"torch\lib\fbgemm.dll",
        r"torch\lib\asmjit.dll",
        r"torch\lib\uv.dll",
    ]

    @unittest.skipUnless(
        (_REPO_ROOT / "speakeasy-cpu.spec").is_file(),
        "speakeasy-cpu.spec not present",
    )
    def test_all_cuda_dlls_stripped(self):
        """Every known CUDA/NVIDIA DLL must be caught by CPU strip patterns."""
        patterns = self._parse_cpu_strip_patterns()
        missed = []
        for dll in self._CUDA_DLLS:
            if not any(p.search(dll) for p in patterns):
                missed.append(dll)
        self.assertEqual(
            missed,
            [],
            "CPU spec strip patterns miss these CUDA DLLs (torch will try "
            "to load them and crash with WinError 126):\n"
            + "\n".join(f"  {d}" for d in missed),
        )

    @unittest.skipUnless(
        (_REPO_ROOT / "speakeasy-cpu.spec").is_file(),
        "speakeasy-cpu.spec not present",
    )
    def test_cpu_essential_dlls_not_stripped(self):
        """CPU-essential torch DLLs must survive the strip pass."""
        patterns = self._parse_cpu_strip_patterns()
        for dll in self._CPU_KEEP:
            for pat in patterns:
                self.assertIsNone(
                    pat.search(dll),
                    f"CPU strip r'{pat.pattern}' would remove essential '{dll}'.",
                )

    # Python modules that torch.backends.__init__ imports unconditionally.
    # These appear in a.pure as dotted module names; CUDA strip patterns
    # must NOT be applied to a.pure or they'll be deleted.
    _TORCH_BACKEND_MODULES = [
        "torch.backends.cudnn",
        "torch.backends.cudnn.rnn",
        "torch.backends.cuda",
        "torch.backends.mkl",
        "torch.backends.mkldnn",
        "torch.backends.openmp",
    ]

    @unittest.skipUnless(
        (_REPO_ROOT / "speakeasy-cpu.spec").is_file(),
        "speakeasy-cpu.spec not present",
    )
    def test_cuda_strip_patterns_not_applied_to_pure(self):
        """CUDA binary patterns must only filter a.binaries, not a.pure.

        torch.backends.__init__ unconditionally imports modules like
        torch.backends.cudnn.  If CUDA patterns (e.g. r'cudnn') are
        applied to a.pure, these Python stubs are stripped and the frozen
        CPU build crashes with ImportError.
        """
        spec_text = self._CPU_SPEC.read_text(encoding="utf-8")

        # Verify the spec uses separate pattern lists and only applies
        # _CUDA_BINARY_PATTERNS to a.binaries, not a.pure or a.datas.
        self.assertIn(
            "_CUDA_BINARY_PATTERNS",
            spec_text,
            "CPU spec must define a separate _CUDA_BINARY_PATTERNS list "
            "for binary-only stripping.",
        )
        # a.pure must NOT be filtered with _CUDA_BINARY_PATTERNS
        for line in spec_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("a.pure") and "=" in stripped:
                self.assertNotIn(
                    "_CUDA_BINARY_PATTERNS", stripped,
                    "a.pure must not be filtered with _CUDA_BINARY_PATTERNS â€” "
                    "this would strip torch.backends.cudnn and other Python stubs.",
                )
            if stripped.startswith("a.datas") and "=" in stripped:
                self.assertNotIn(
                    "_CUDA_BINARY_PATTERNS", stripped,
                    "a.datas must not be filtered with _CUDA_BINARY_PATTERNS.",
                )

    @unittest.skipUnless(
        (_REPO_ROOT / "speakeasy-cpu.spec").is_file(),
        "speakeasy-cpu.spec not present",
    )
    def test_general_strip_patterns_spare_torch_backend_modules(self):
        """_STRIP_PATTERNS (applied to a.pure) must not match torch backend modules."""
        spec_text = self._CPU_SPEC.read_text(encoding="utf-8")
        # Parse only _STRIP_PATTERNS (before _CUDA_BINARY_PATTERNS block)
        cuda_block = spec_text.find("_CUDA_BINARY_PATTERNS")
        strip_section = spec_text[:cuda_block] if cuda_block != -1 else spec_text
        raw = re.findall(r"_re\.compile\(r'([^']+)'", strip_section)
        patterns = [re.compile(p, re.I) for p in raw]

        for mod in self._TORCH_BACKEND_MODULES:
            for pat in patterns:
                self.assertIsNone(
                    pat.search(mod),
                    f"CPU _STRIP_PATTERNS r'{pat.pattern}' would strip "
                    f"Python module '{mod}' from a.pure.",
                )


class TestCertifiSslBundle(unittest.TestCase):
    """certifi's CA bundle must be collected so OpenAI/httpx SSL works in frozen builds.

    Without collect_data_files('certifi'), ssl.create_default_context(cafile=certifi.where())
    raises FileNotFoundError in the frozen app because cacert.pem is not copied by
    PyInstaller's import analysis alone.
    """

    def _read_spec(self, name: str) -> str:
        path = _REPO_ROOT / name
        self.assertTrue(path.is_file(), f"{name} not found")
        return path.read_text(encoding="utf-8")

    def test_gpu_spec_collects_certifi_data(self):
        """speakeasy.spec must call collect_data_files('certifi')."""
        spec = self._read_spec("speakeasy.spec")
        self.assertIn(
            "collect_data_files('certifi')",
            spec,
            "speakeasy.spec must include collect_data_files('certifi') — "
            "omitting it causes FileNotFoundError when OpenAI/httpx creates an SSL context.",
        )

    def test_cpu_spec_collects_certifi_data(self):
        """speakeasy-cpu.spec must call collect_data_files('certifi')."""
        spec = self._read_spec("speakeasy-cpu.spec")
        self.assertIn(
            "collect_data_files('certifi')",
            spec,
            "speakeasy-cpu.spec must include collect_data_files('certifi') — "
            "omitting it causes FileNotFoundError when OpenAI/httpx creates an SSL context.",
        )

    def test_runtime_hook_sets_ssl_cert_file(self):
        """Runtime hook must set SSL_CERT_FILE to the bundled certifi CA bundle."""
        hook = _SPEAKEASY_PKG / "_runtime_hook_dll.py"
        source = hook.read_text(encoding="utf-8")
        self.assertIn(
            "SSL_CERT_FILE",
            source,
            "_runtime_hook_dll.py must set SSL_CERT_FILE so httpx finds the "
            "certifi CA bundle before any SSL connection is attempted.",
        )
        self.assertIn(
            "cacert.pem",
            source,
            "_runtime_hook_dll.py must reference cacert.pem to locate the "
            "certifi CA bundle inside _MEIPASS.",
        )

    def test_runtime_hook_sets_requests_ca_bundle(self):
        """Runtime hook must also set REQUESTS_CA_BUNDLE for requests-based clients."""
        hook = _SPEAKEASY_PKG / "_runtime_hook_dll.py"
        source = hook.read_text(encoding="utf-8")
        self.assertIn(
            "REQUESTS_CA_BUNDLE",
            source,
            "_runtime_hook_dll.py must set REQUESTS_CA_BUNDLE alongside SSL_CERT_FILE.",
        )

    def test_strip_patterns_do_not_remove_certifi_bundle(self):
        """Certifi's cacert.pem must not be accidentally stripped from the build."""
        spec = self._read_spec("speakeasy.spec")
        raw_patterns = re.findall(r"_re\.compile\(r'([^']+)'", spec)
        patterns = [re.compile(p, re.I) for p in raw_patterns]
        cacert_entry = "certifi/cacert.pem"
        for pat in patterns:
            self.assertIsNone(
                pat.search(cacert_entry),
                f"Strip r'{pat.pattern}' would accidentally remove certifi/cacert.pem.",
            )

    def test_certifi_importable(self):
        """certifi must be importable (sanity check that it is installed)."""
        try:
            import certifi
            bundle = certifi.where()
            self.assertTrue(
                os.path.isfile(bundle),
                f"certifi.where() returned '{bundle}' which does not exist — "
                "run 'uv sync' to ensure certifi is installed.",
            )
        except ImportError:
            self.fail(
                "certifi is not importable — add it to pyproject.toml dependencies "
                "or ensure it is pulled in transitively via openai/httpx."
            )


