"""Tests for engine loading, model file detection, and registry."""

import os
import tempfile
import unittest
from pathlib import Path

from speakeasy.engine import ENGINES, _model_files_exist, get_available_engines


class TestEngineRegistry(unittest.TestCase):
    """Engine registry must contain Granite as the only engine."""

    def test_granite_registered(self):
        self.assertIn("granite", ENGINES)

    def test_only_granite_registered(self):
        self.assertEqual(list(ENGINES.keys()), ["granite"])

    def test_granite_engine_name(self):
        engine = ENGINES["granite"]()
        self.assertEqual(engine.name, "granite")

    def test_granite_vram_estimate(self):
        engine = ENGINES["granite"]()
        self.assertGreater(engine.vram_estimate_gb, 0)


class TestModelFileDetection(unittest.TestCase):
    """Model file detection must correctly identify present/absent models."""

    def test_granite_with_config(self):
        with tempfile.TemporaryDirectory() as d:
            granite_dir = os.path.join(d, "granite")
            os.makedirs(granite_dir)
            with open(os.path.join(granite_dir, "config.json"), "w") as f:
                f.write("{}")
            self.assertTrue(_model_files_exist("granite", d))

    def test_granite_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            granite_dir = os.path.join(d, "granite")
            os.makedirs(granite_dir)
            self.assertFalse(_model_files_exist("granite", d))

    def test_granite_no_directory(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(_model_files_exist("granite", d))

    def test_unknown_engine(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(_model_files_exist("nonexistent", d))


class TestGetAvailableEngines(unittest.TestCase):
    """get_available_engines must only return engines with model files."""

    def test_granite_present(self):
        with tempfile.TemporaryDirectory() as d:
            granite_dir = os.path.join(d, "granite")
            os.makedirs(granite_dir)
            with open(os.path.join(granite_dir, "config.json"), "w") as f:
                f.write("{}")
            available = get_available_engines(d)
            self.assertIn("granite", available)

    def test_none_present(self):
        with tempfile.TemporaryDirectory() as d:
            available = get_available_engines(d)
            self.assertEqual(available, [])


if __name__ == "__main__":
    unittest.main()
"""Tests for engine loading, model file detection, and registry."""

import os
import tempfile

