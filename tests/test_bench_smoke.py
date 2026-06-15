"""Smoke tests for the Phase 0 benchmark harness (tools/bench.py).

Keeps the harness from rotting: ``--smoke`` must run with no torch, no
transformers, and no downloaded model, and must emit a JSON report matching
the committed schema.  Also unit-tests the WER and percentile helpers.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BENCH = _REPO_ROOT / "tools" / "bench.py"
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "audio"


def _load_bench_module():
    spec = importlib.util.spec_from_file_location("speakeasy_bench", _BENCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass field resolution can find the module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestBenchHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bench = _load_bench_module()

    def test_wer_identical(self):
        self.assertEqual(self.bench._wer("one two three", "one two three"), 0.0)

    def test_wer_one_substitution(self):
        # 1 error over 3 reference words.
        self.assertAlmostEqual(self.bench._wer("one two three", "one four three"), 1 / 3)

    def test_wer_empty_reference(self):
        self.assertEqual(self.bench._wer("", ""), 0.0)
        self.assertEqual(self.bench._wer("", "extra"), 1.0)

    def test_percentile_single_value(self):
        self.assertEqual(self.bench._percentile([0.5], 95), 0.5)

    def test_percentile_p50(self):
        self.assertAlmostEqual(self.bench._percentile([1.0, 2.0, 3.0], 50), 2.0)


class TestFixturesPresent(unittest.TestCase):
    def test_synthetic_fixtures_exist(self):
        for name in ("10s.wav", "30s.wav", "120s.wav"):
            self.assertTrue(
                (_FIXTURE_DIR / name).is_file(),
                f"Missing fixture {name}; run tests/fixtures/audio/generate_fixtures.py",
            )

    def test_references_parse(self):
        refs = json.loads((_FIXTURE_DIR / "references.json").read_text(encoding="utf-8"))
        self.assertIn("validation.wav", refs)
        self.assertIsNone(refs["10s.wav"])


class TestBenchSmokeRun(unittest.TestCase):
    def test_smoke_run_emits_valid_report(self):
        out = _REPO_ROOT / "tests" / "fixtures" / "audio" / "_smoke_out.json"
        try:
            proc = subprocess.run(
                [sys.executable, str(_BENCH), "--smoke", "--device", "cpu",
                 "--output", str(out)],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(report["smoke"])
            self.assertEqual(report["device"], "cpu")
            self.assertEqual(report["engine"]["name"], "smoke")
            self.assertEqual(report["schema_version"], 1)
            self.assertGreaterEqual(len(report["fixtures"]), 3)
            for fixture in report["fixtures"]:
                self.assertIn("p50_latency_s", fixture)
                self.assertIn("rtf", fixture)
                self.assertGreater(fixture["duration_s"], 0)
        finally:
            out.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
