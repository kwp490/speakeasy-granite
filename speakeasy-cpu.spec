# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SpeakEasy AI Granite — CPU-only variant (no CUDA/GPU).

Thin shim over ``spec_common.build()`` with the CPU default. The CPU build
skips bundling torch's CUDA DLLs, strips any CUDA/NVIDIA binaries, and drops
pynvml/torchaudio (see ``spec_common``). The active variant is baked into the
bundle as a ``_variant_tag`` marker read by ``speakeasy/_build_variant.py`` —
this file no longer live-patches ``_build_variant.py``.

Build:  pyinstaller speakeasy-cpu.spec
        pyinstaller speakeasy-cpu.spec -- --variant cpu   (explicit; same result)
Output: dist/speakeasy-cpu/speakeasy.exe (onedir)

Note: Build-Installer.ps1 installs CPU-only torch wheels before invoking this
spec so the bundled torch DLLs carry no CUDA references.
"""

import sys

# SPECPATH is the directory containing this spec (repo root); put it on sys.path
# so ``import spec_common`` resolves regardless of the invoking CWD.
if SPECPATH not in sys.path:
    sys.path.insert(0, SPECPATH)

import spec_common

spec_common.build(default_variant="cpu")
