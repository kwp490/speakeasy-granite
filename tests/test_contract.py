"""Tests for the transcription contract data types and torch-free import.

The core layer must import cleanly in an interpreter where torch/transformers/
librosa are not importable.  This is the Phase 1 down-payment on the Phase 2
import-isolation guarantee.
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest

from speakeasy.core import contract


def test_contract_version_is_int():
    assert isinstance(contract.CONTRACT_VERSION, int)
    assert contract.CONTRACT_VERSION >= 1


@pytest.mark.parametrize(
    "cls",
    [
        contract.EngineDescriptor,
        contract.EngineCapabilities,
        contract.TranscriptionOptions,
        contract.TranscriptionResult,
        contract.LoadReport,
        contract.HealthReport,
        contract.EngineStats,
    ],
)
def test_dataclasses_are_frozen(cls):
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen is True


def test_transcription_options_defaults():
    opts = contract.TranscriptionOptions()
    assert opts.task == "transcribe"
    assert opts.language == "en"
    assert opts.punctuation is True
    assert opts.timeout_s == 30.0


def test_transcription_result_defaults():
    result = contract.TranscriptionResult(text="hi")
    assert result.text == "hi"
    assert result.tokens_generated == 0
    assert result.device == "cpu"


def test_runtime_checkable_protocol_accepts_inprocess_service():
    from speakeasy.engines.fake import FakeEngine
    from speakeasy.services.inprocess import InProcessEngineService

    service = InProcessEngineService(FakeEngine())
    assert isinstance(service, contract.TranscriptionService)


def test_core_imports_without_ml_packages():
    """`import speakeasy.core.*` must succeed with torch/transformers/librosa blocked."""
    blocker = (
        "import sys, importlib.abc, importlib.machinery\n"
        "BLOCKED = {'torch', 'transformers', 'librosa', 'accelerate', 'PySide6'}\n"
        "class Blocker(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path, target=None):\n"
        "        top = name.split('.')[0]\n"
        "        if top in BLOCKED:\n"
        "            raise ImportError(f'blocked: {name}')\n"
        "        return None\n"
        "sys.meta_path.insert(0, Blocker())\n"
        "import speakeasy.core.contract\n"
        "import speakeasy.core.errors\n"
        "import speakeasy.core.model_source\n"
        "import speakeasy.core.resample\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", blocker],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout
