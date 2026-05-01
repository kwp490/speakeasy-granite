# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for SpeakEasy AI Granite — CPU-only variant (no CUDA/GPU).

Build: pyinstaller speakeasy-cpu.spec
Output: dist/speakeasy-cpu/speakeasy.exe (onedir)

This spec produces a smaller bundle by excluding CUDA libraries,
nvidia-ml-py, and torchaudio.  The _build_variant.py file is patched
to VARIANT = "cpu" before Analysis so runtime code adapts automatically.
"""

import os as _os

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

block_cipher = None

# ── Patch _build_variant.py to "cpu" for this build ─────────────────────────
_variant_path = _os.path.join('speakeasy', '_build_variant.py')
_variant_backup = None
if _os.path.isfile(_variant_path):
    with open(_variant_path, 'r', encoding='utf-8') as _f:
        _variant_backup = _f.read()
    with open(_variant_path, 'w', encoding='utf-8') as _f:
        _f.write('"""Build variant flag — patched at build time by the CPU PyInstaller spec."""\n\n'
                 'VARIANT = "cpu"  # "gpu" (default) or "cpu"\n')

# Collect PortAudio DLL from sounddevice
binaries = collect_dynamic_libs('sounddevice')

# CPU build: skip collect_dynamic_libs('torch') — no CUDA DLLs needed.
# torch's core DLLs (torch_cpu.dll etc.) are collected automatically by
# PyInstaller's import analysis.

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
# Without this, ssl.create_default_context(cafile=certifi.where()) raises
# FileNotFoundError because cacert.pem is not copied by import analysis alone.
try:
    datas += collect_data_files('certifi')
except Exception:
    pass

a = Analysis(
    ['speakeasy/__main__.py'],
    pathex=[],
    binaries=binaries,
    datas=datas + [
        ('speakeasy/assets', 'speakeasy/assets'),
    ],
    hiddenimports=[
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtSvg',
        'sounddevice',
        'soundfile',
        '_soundfile_data',
        'numpy',
        'keyboard',
        # pynvml excluded — CPU build does not monitor GPU
        'transformers',
        'accelerate',
        'torch',
        'torch._strobelight',
        'torch._strobelight.compile_time_profiler',
        # torchaudio excluded — not used at runtime
        'huggingface_hub',
        'sentencepiece',
        'protobuf',
        'tokenizers',
        'librosa',
        'safetensors',
    ],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=['speakeasy/_runtime_hook_dll.py'],
    excludes=[
        # GPU / NVIDIA packages not used in CPU build
        'pynvml',
        'nvidia',
        'torchaudio',
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
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ── Strip unnecessary bundled files ──────────────────────────────────────────
import re as _re

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

# ── CUDA / NVIDIA binary-only patterns ────────────────────────────────────
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

def _entry_name(entry):
    return entry[0] if isinstance(entry, tuple) else str(entry)


def _should_keep(entry, patterns=_STRIP_PATTERNS):
    name = _entry_name(entry)
    return not any(p.search(name) for p in patterns)


def _filter_entries(entries, patterns=_STRIP_PATTERNS):
    return [entry for entry in entries if _should_keep(entry, patterns)]


a.pure = _filter_entries(a.pure)
a.binaries = _filter_entries(_filter_entries(a.binaries), _CUDA_BINARY_PATTERNS)
a.datas = _filter_entries(a.datas)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Restore _build_variant.py after PYZ compilation ─────────────────────────
# Must happen AFTER PYZ() which compiles Python modules into bytecode.
# Restoring earlier (e.g. after Analysis) causes PYZ to compile the restored
# "gpu" source instead of the patched "cpu" source.
if _variant_backup is not None:
    with open(_variant_path, 'w', encoding='utf-8') as _f:
        _f.write(_variant_backup)

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
    name='speakeasy-cpu',
)
