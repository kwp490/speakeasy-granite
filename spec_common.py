# -*- coding: utf-8 -*-
"""Shared PyInstaller build logic for the SpeakEasy GPU and CPU specs.

``speakeasy.spec`` and ``speakeasy-cpu.spec`` are thin shims that call
:func:`build`. The active variant comes from a ``--variant {gpu,cpu}`` argument
passed to PyInstaller after ``--`` (falling back to the shim's default), and is
baked into the frozen bundle as a one-line ``_variant_tag`` marker that
``speakeasy/_build_variant.py`` reads at runtime — no tracked source file is
mutated (the old CPU spec live-patched ``_build_variant.py`` during Analysis).

Import-safety: this module is importable without PyInstaller installed. Only
:func:`build` (and the ``collect_*`` helpers it calls) touch PyInstaller. The
data constants and the :func:`hidden_imports` / :func:`excludes` /
:func:`strip_patterns` helpers are pure and are consumed by the build-invariant
tests (``tests/test_frozen_layout.py``, ``tests/test_frozen_ml_isolation.py``,
``tests/test_build_naming.py``).
"""

from __future__ import annotations

import os
import re as _re
import sys
import tempfile

VARIANTS = ("gpu", "cpu")

# ── hiddenimports ────────────────────────────────────────────────────────────
# GPU superset. The CPU build drops the GPU-only modules (see hidden_imports()):
#   - pynvml      : NVIDIA GPU telemetry, unused on CPU
#   - torchaudio  : not used at runtime in the CPU bundle
hiddenimports = [
    'PySide6.QtWidgets',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtSvg',
    'sounddevice',
    'soundfile',
    '_soundfile_data',
    'numpy',
    'pynvml',
    'transformers',
    'accelerate',
    'torch',
    'torch._strobelight',
    'torch._strobelight.compile_time_profiler',
    'torchaudio',
    'huggingface_hub',
    'hf_xet',
    'sentencepiece',
    'protobuf',
    'tokenizers',
    'soxr',
    'safetensors',
]
_CPU_DROP_HIDDEN = ('pynvml', 'torchaudio')

# ── excludes ─────────────────────────────────────────────────────────────────
# GPU base. The CPU build prepends pynvml / nvidia / torchaudio (see excludes()).
excludes = [
    # GUI / image libraries not used
    'tkinter',
    'matplotlib',
    'pandas',
    'PIL',
    'sklearn',
    # Qt submodules not used (only QtWidgets/QtCore/QtGui needed)
    'PySide6.QtQuick',
    'PySide6.QtQml',
    'PySide6.QtPdf',
    # ── Transformers submodules not used ───────────────────────────
    'transformers.pipelines',
    'transformers.trainer',
    'transformers.trainer_seq2seq',
    'transformers.trainer_callback',
    'transformers.trainer_pt_utils',
    'transformers.trainer_utils',
    'transformers.training_args',
    'transformers.training_args_seq2seq',
    'transformers.optimization',
    # Model families not used by the Granite-only runtime
    'transformers.models.whisper',
    'transformers.models.nemotron',
    'transformers.models.nemotron_h',
    # ── Dev / build tools not needed at runtime ────────────────────
    'setuptools',
    'pkg_resources',
    'pytest',
    '_pytest',
]
_CPU_ADD_EXCLUDES = ('pynvml', 'nvidia', 'torchaudio')

# ── strip patterns (shared, no CUDA) ─────────────────────────────────────────
# Applied to a.pure / a.binaries / a.datas for both variants.
_STRIP_PATTERNS = [
    # Qt modules not used by the app
    _re.compile(r'Qt6Quick', _re.I),
    _re.compile(r'Qt6Qml', _re.I),
    _re.compile(r'Qt6Pdf', _re.I),
    _re.compile(r'Qt6VirtualKeyboard', _re.I),
    _re.compile(r'Qt6OpenGL', _re.I),
    _re.compile(r'opengl32sw', _re.I),
    # Qt translations and plugins not used by the app
    _re.compile(r'PySide6[\\/]translations[\\/]', _re.I),
    _re.compile(r'PySide6[\\/]plugins[\\/]platforminputcontexts[\\/]qtvirtualkeyboardplugin', _re.I),
    _re.compile(r'PySide6[\\/]plugins[\\/]networkinformation[\\/]qnetworklistmanager', _re.I),
    _re.compile(r'PySide6[\\/]plugins[\\/]imageformats[\\/](?:qpdf|qicns|qtga|qtiff|qwbmp|qwebp)\.dll', _re.I),
    # Unused transformer model families that otherwise create stale bundle payloads
    _re.compile(r'transformers(?:[\\/.]|$)models(?:[\\/.])whisper(?:[\\/.]|$)', _re.I),
    _re.compile(r'transformers(?:[\\/.]|$)models(?:[\\/.])nemotron(?:_h)?(?:[\\/.]|$)', _re.I),
    # sklearn is not used by the active Granite path; drop any leftover package/data payload
    _re.compile(r'(?:^|[\\/])sklearn[\\/]', _re.I),
    _re.compile(r'(?:^|[\\/])scikit_learn-[^\\/]+\.dist-info[\\/]', _re.I),
    # Duplicate / dev binaries in torch/bin
    _re.compile(r'torch[\\/]bin[\\/]asmjit', _re.I),
    _re.compile(r'torch[\\/]bin[\\/]fbgemm', _re.I),
    _re.compile(r'protoc\.exe', _re.I),
]

# ── CUDA / NVIDIA binary-only patterns (CPU build only) ──────────────────────
# Applied only to a.binaries so that Python stub modules like
# torch.backends.cudnn (needed by torch.backends.__init__) survive in a.pure.
_CUDA_BINARY_PATTERNS = [
    _re.compile(r'cublas', _re.I),
    _re.compile(r'cublasLt', _re.I),
    _re.compile(r'cudart', _re.I),
    _re.compile(r'cudnn', _re.I),
    _re.compile(r'cufft', _re.I),
    _re.compile(r'curand', _re.I),
    _re.compile(r'cusolver', _re.I),
    _re.compile(r'cusparse', _re.I),
    _re.compile(r'nccl', _re.I),
    _re.compile(r'nvrtc', _re.I),
    _re.compile(r'nvJitLink', _re.I),
    _re.compile(r'nvperf', _re.I),
    _re.compile(r'nvToolsExt', _re.I),
    _re.compile(r'nvidia[\\/]', _re.I),
    _re.compile(r'torch[\\/]lib[\\/]cu', _re.I),
    _re.compile(r'c10_cuda', _re.I),
    _re.compile(r'torch_cuda', _re.I),
    _re.compile(r'caffe2_nvrtc', _re.I),
]


# ── pure helpers (no PyInstaller required) ───────────────────────────────────

def _normalize_variant(variant: str) -> str:
    v = (variant or "").strip().lower()
    return v if v in VARIANTS else "gpu"


def hidden_imports(variant: str = "gpu") -> list:
    """hiddenimports for ``variant`` (GPU superset minus CPU-only modules)."""
    variant = _normalize_variant(variant)
    if variant == "cpu":
        return [m for m in hiddenimports if m not in _CPU_DROP_HIDDEN]
    return list(hiddenimports)


def excludes_for(variant: str = "gpu") -> list:
    """excludes for ``variant`` (CPU prepends pynvml/nvidia/torchaudio)."""
    variant = _normalize_variant(variant)
    if variant == "cpu":
        return list(_CPU_ADD_EXCLUDES) + list(excludes)
    return list(excludes)


def strip_patterns(variant: str = "gpu") -> list:
    """Compiled strip patterns for ``variant``.

    GPU = the shared (no-CUDA) set. CPU = the shared set plus the CUDA/NVIDIA
    binary patterns (which the CPU build applies to ``a.binaries`` only).
    """
    variant = _normalize_variant(variant)
    pats = list(_STRIP_PATTERNS)
    if variant == "cpu":
        pats += _CUDA_BINARY_PATTERNS
    return pats


def cuda_binary_patterns() -> list:
    """The CUDA/NVIDIA binary strip patterns (CPU build, ``a.binaries`` only)."""
    return list(_CUDA_BINARY_PATTERNS)


def resolve_variant(default: str = "gpu") -> str:
    """Resolve the build variant from ``--variant {gpu,cpu}`` in ``sys.argv``.

    PyInstaller forwards arguments after ``--`` into ``sys.argv``. When no
    ``--variant`` is present (e.g. ``pyinstaller speakeasy.spec`` run directly),
    the shim's ``default`` is used, so each spec still builds its own variant.
    """
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--variant" and i + 1 < len(argv):
            cand = argv[i + 1].strip().lower()
            if cand in VARIANTS:
                return cand
        elif arg.startswith("--variant="):
            cand = arg.split("=", 1)[1].strip().lower()
            if cand in VARIANTS:
                return cand
    return _normalize_variant(default)


def _write_variant_marker(variant: str) -> str:
    """Write the ``_variant_tag`` marker to a temp dir; return its path.

    Added to the Analysis ``datas`` so the frozen bundle ships
    ``<bundle>/_variant_tag`` for ``speakeasy/_build_variant.py`` to read.
    """
    tmpdir = tempfile.mkdtemp(prefix="speakeasy_variant_")
    marker = os.path.join(tmpdir, "_variant_tag")
    with open(marker, "w", encoding="utf-8") as fh:
        fh.write(variant + "\n")
    return marker


# ── the build (PyInstaller required) ─────────────────────────────────────────

def build(default_variant: str = "gpu"):
    """Run the PyInstaller Analysis/PYZ/EXE/COLLECT pipeline for one variant."""
    from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files
    from PyInstaller.building.build_main import Analysis
    from PyInstaller.building.api import PYZ, EXE, COLLECT

    variant = resolve_variant(default_variant)
    is_cpu = variant == "cpu"
    block_cipher = None

    # Collect PortAudio DLL from sounddevice
    binaries = collect_dynamic_libs('sounddevice')

    # GPU build: bundle all of torch's native libs (shm.dll and its deps).
    # CPU build skips this — torch's core CPU DLLs are picked up by import
    # analysis and the CUDA DLLs are stripped below.
    if not is_cpu:
        binaries += collect_dynamic_libs('torch')

    # transformers>=5.5 scans transformers/models on disk from __init__.py,
    # and Auto* helpers reach cross-model packages like encoder_decoder during
    # normal Granite loading. Keep the root __init__.py and the models tree as
    # real .py files under _internal/transformers instead of only in the PYZ.
    datas = []
    try:
        datas += collect_data_files('transformers', include_py_files=False)
    except Exception:
        pass

    for _subpkg, _kwargs in (
        ('transformers', {'include_py_files': True, 'includes': ['__init__.py']}),
        ('transformers.models', {'include_py_files': True}),
    ):
        try:
            datas += collect_data_files(_subpkg, **_kwargs)
        except Exception:
            pass

    # Collect certifi's CA bundle so httpx/OpenAI SSL works in the frozen build.
    try:
        datas += collect_data_files('certifi')
    except Exception:
        pass

    # Hugging Face uses hf_xet for Xet-backed repos such as IBM Granite Speech.
    try:
        binaries += collect_dynamic_libs('hf_xet')
    except Exception:
        pass

    # Bake the build variant into the bundle (no source mutation).
    variant_marker = _write_variant_marker(variant)

    a = Analysis(
        ['speakeasy/__main__.py'],
        pathex=[],
        binaries=binaries,
        datas=datas + [
            ('speakeasy/assets', 'speakeasy/assets'),
            (variant_marker, '.'),
        ],
        hiddenimports=hidden_imports(variant),
        hookspath=['hooks'],
        hooksconfig={},
        runtime_hooks=['speakeasy/_runtime_hook_dll.py'],
        excludes=excludes_for(variant),
        win_no_prefer_redirects=False,
        win_private_assemblies=False,
        cipher=block_cipher,
        noarchive=False,
    )

    # ── Strip unnecessary bundled files ──────────────────────────────────────
    def _entry_name(entry):
        return entry[0] if isinstance(entry, tuple) else str(entry)

    def _should_keep(entry, patterns):
        name = _entry_name(entry)
        return not any(p.search(name) for p in patterns)

    def _filter_entries(entries, patterns=_STRIP_PATTERNS):
        return [entry for entry in entries if _should_keep(entry, patterns)]

    a.pure = _filter_entries(a.pure)
    if is_cpu:
        # CUDA DLLs must be stripped only from a.binaries so torch's pure-Python
        # backend stubs survive. Torch's _load_dll_libraries() globs torch/lib;
        # any surviving CUDA DLL crashes the CPU build with WinError 126.
        a.binaries = _filter_entries(_filter_entries(a.binaries), _CUDA_BINARY_PATTERNS)
    else:
        a.binaries = _filter_entries(a.binaries)
    a.datas = _filter_entries(a.datas)

    pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='speakeasy',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        icon='speakeasy/assets/app.ico',
        console=False,
        disable_windowed_traceback=False,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='speakeasy-cpu' if is_cpu else 'speakeasy',
    )

    return coll
