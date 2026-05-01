"""Tests for the SpeechEngine abstract base class contract."""

import unittest
from unittest.mock import MagicMock

import numpy as np

from speakeasy.engine.base import SpeechEngine


class _StubEngine(SpeechEngine):
    """Minimal concrete subclass for testing the ABC contract."""

    @property
    def name(self) -> str:
        return "stub"

    @property
    def vram_estimate_gb(self) -> float:
        return 1.0

    def load(self, model_path: str, device: str = "cuda") -> None:
        self._model = MagicMock()

    def _transcribe_impl(self, audio_16k: np.ndarray, language: str,
                          punctuation: bool = True,
                          timeout: float = 30.0,
                          partial_callback=None) -> str:
        self.last_kwargs = {
            "language": language,
            "punctuation": punctuation,
            "timeout": timeout,
            "partial_callback": partial_callback,
        }
        return "hello world"

    def unload(self) -> None:
        self._release_model()


class TestSpeechEngineContract(unittest.TestCase):
    """Verify the SpeechEngine ABC provides correct shared behaviour."""

    def test_initial_state_not_loaded(self):
        engine = _StubEngine()
        self.assertFalse(engine.is_loaded)

    def test_is_loaded_after_load(self):
        engine = _StubEngine()
        engine.load("/dummy")
        self.assertTrue(engine.is_loaded)

    def test_not_loaded_after_unload(self):
        engine = _StubEngine()
        engine.load("/dummy")
        engine.unload()
        self.assertFalse(engine.is_loaded)

    def test_transcribe_raises_when_not_loaded(self):
        engine = _StubEngine()
        audio = np.zeros(16000, dtype=np.float32)
        with self.assertRaises(RuntimeError):
            engine.transcribe(audio, 16000)

    def test_transcribe_returns_text_when_loaded(self):
        engine = _StubEngine()
        engine.load("/dummy")
        audio = np.zeros(16000, dtype=np.float32)
        result = engine.transcribe(audio, 16000)
        self.assertEqual(result, "hello world")

    def test_transcribe_empty_audio_returns_empty(self):
        engine = _StubEngine()
        engine.load("/dummy")
        audio = np.array([], dtype=np.float32)
        result = engine.transcribe(audio, 16000)
        self.assertEqual(result, "")

    def test_name_property(self):
        engine = _StubEngine()
        self.assertEqual(engine.name, "stub")

    def test_vram_estimate(self):
        engine = _StubEngine()
        self.assertEqual(engine.vram_estimate_gb, 1.0)

    def test_transcribe_forwards_partial_callback(self):
        """``partial_callback`` must be passed through untouched to ``_transcribe_impl``."""
        engine = _StubEngine()
        engine.load("/dummy")
        cb = lambda text, i, n: None  # noqa: E731
        audio = np.zeros(16000, dtype=np.float32)
        engine.transcribe(audio, 16000, partial_callback=cb)
        self.assertIs(engine.last_kwargs["partial_callback"], cb)

    def test_transcribe_default_partial_callback_is_none(self):
        engine = _StubEngine()
        engine.load("/dummy")
        audio = np.zeros(16000, dtype=np.float32)
        engine.transcribe(audio, 16000)
        self.assertIsNone(engine.last_kwargs["partial_callback"])


class TestEngineRegistryHasEngines(unittest.TestCase):
    """The engine registry must contain at least one engine."""

    def test_engines_dict_not_empty(self):
        from speakeasy.engine import ENGINES
        self.assertIsInstance(ENGINES, dict)
        self.assertIn("cohere", ENGINES)
        self.assertEqual(len(ENGINES), 1)

    def test_cohere_is_speech_engine(self):
        from speakeasy.engine import ENGINES
        from speakeasy.engine.base import SpeechEngine
        self.assertTrue(issubclass(ENGINES["cohere"], SpeechEngine))

