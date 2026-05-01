# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for SpeakEasy AI — Cohere Transcribe engine (transformers/torch).

Build: pyinstaller speakeasy.spec
Output: dist/speakeasy/speakeasy.exe (onedir)
"""

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

block_cipher = None

# Collect PortAudio DLL from sounddevice
binaries = collect_dynamic_libs('sounddevice')

# Collect all native libs from torch so shm.dll and its deps are bundled
binaries += collect_dynamic_libs('torch')

# transformers>=5.5 scans transformers/models on disk from __init__.py,
# and Auto* helpers reach cross-model packages like encoder_decoder during
# normal Cohere loading. Keep the root __init__.py and the models tree as
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
        'pynvml',
        'transformers',
        'accelerate',
        'torch',
        'torch._strobelight',
        'torch._strobelight.compile_time_profiler',
        'torchaudio',
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
        # Model families not used by the Cohere-only runtime
        'transformers.models.whisper',
        'transformers.models.nemotron',
        'transformers.models.nemotron_h',
        'transformers.models.granite',
        'transformers.models.granite_speech',
        'transformers.models.granitemoe',
        'transformers.models.granitemoehybrid',
        'transformers.models.granitemoeshared',
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
    _re.compile(r'transformers(?:[\\/.]|$)models(?:[\\/.])granite(?:_speech|moe(?:hybrid|shared)?)?(?:[\\/.]|$)', _re.I),
    # sklearn is not used by the active Cohere path; drop any leftover package/data payload
    _re.compile(r'(?:^|[\\/])sklearn[\\/]', _re.I),
    _re.compile(r'(?:^|[\\/])scikit_learn-[^\\/]+\.dist-info[\\/]', _re.I),
    # Duplicate / dev binaries in torch/bin
    _re.compile(r'torch[\\/]bin[\\/]asmjit', _re.I),
    _re.compile(r'torch[\\/]bin[\\/]fbgemm', _re.I),
    _re.compile(r'protoc\.exe', _re.I),
]

def _entry_name(entry):
    return entry[0] if isinstance(entry, tuple) else str(entry)


def _should_keep(entry):
    name = _entry_name(entry)
    return not any(p.search(name) for p in _STRIP_PATTERNS)


def _filter_entries(entries):
    return [entry for entry in entries if _should_keep(entry)]


a.pure = _filter_entries(a.pure)
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
    name='speakeasy',
)
