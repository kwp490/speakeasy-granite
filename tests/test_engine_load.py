"""Tests for engine loading, model file detection, and registry."""

import os
import tempfile
import unittest
from pathlib import Path

from speakeasy.engine import ENGINES, _model_files_exist, get_available_engines


class TestEngineRegistry(unittest.TestCase):
    """Engine registry must contain Cohere as the only engine."""

    def test_cohere_registered(self):
        self.assertIn("cohere", ENGINES)

    def test_only_cohere_registered(self):
        self.assertEqual(list(ENGINES.keys()), ["cohere"])

    def test_cohere_engine_name(self):
        engine = ENGINES["cohere"]()
        self.assertEqual(engine.name, "cohere")

    def test_cohere_vram_estimate(self):
        engine = ENGINES["cohere"]()
        self.assertGreater(engine.vram_estimate_gb, 0)


class TestModelFileDetection(unittest.TestCase):
    """Model file detection must correctly identify present/absent models."""

    def test_cohere_with_config(self):
        with tempfile.TemporaryDirectory() as d:
            cohere_dir = os.path.join(d, "cohere")
            os.makedirs(cohere_dir)
            with open(os.path.join(cohere_dir, "config.json"), "w") as f:
                f.write("{}")
            self.assertTrue(_model_files_exist("cohere", d))

    def test_cohere_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            cohere_dir = os.path.join(d, "cohere")
            os.makedirs(cohere_dir)
            self.assertFalse(_model_files_exist("cohere", d))

    def test_cohere_no_directory(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(_model_files_exist("cohere", d))

    def test_unknown_engine(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(_model_files_exist("nonexistent", d))


class TestGetAvailableEngines(unittest.TestCase):
    """get_available_engines must only return engines with model files."""

    def test_cohere_present(self):
        with tempfile.TemporaryDirectory() as d:
            cohere_dir = os.path.join(d, "cohere")
            os.makedirs(cohere_dir)
            with open(os.path.join(cohere_dir, "config.json"), "w") as f:
                f.write("{}")
            available = get_available_engines(d)
            self.assertIn("cohere", available)

    def test_none_present(self):
        with tempfile.TemporaryDirectory() as d:
            available = get_available_engines(d)
            self.assertEqual(available, [])


if __name__ == "__main__":
    unittest.main()
"""Tests for engine loading, model file detection, and registry."""

import os
import tempfile

