# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SpeakEasy AI Granite — GPU (CUDA) variant.

Thin shim over ``spec_common.build()``. All build logic (binaries, datas,
hiddenimports, excludes, strip patterns, EXE/COLLECT) lives in ``spec_common``
so the GPU and CPU variants share one source of truth.

Build:  pyinstaller speakeasy.spec
        pyinstaller speakeasy.spec -- --variant gpu   (explicit; same result)
Output: dist/speakeasy/speakeasy.exe (onedir)
"""

import sys

# SPECPATH is the directory containing this spec (repo root); put it on sys.path
# so ``import spec_common`` resolves regardless of the invoking CWD.
if SPECPATH not in sys.path:
    sys.path.insert(0, SPECPATH)

import spec_common

spec_common.build(default_variant="gpu")
