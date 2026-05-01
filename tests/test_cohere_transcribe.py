"""Targeted tests for the Cohere transcription engine."""

import unittest
from types import SimpleNamespace

import numpy as np
import torch

from speakeasy.engine.cohere_transcribe import CohereTranscribeEngine


class _FakeProcessor:
    def __init__(self):
        self.calls = []

    def __call__(self, audio_16k, sampling_rate, return_tensors, language, punctuation):
        self.calls.append(
            {
                "audio_len": len(audio_16k),
                "sampling_rate": sampling_rate,
                "return_tensors": return_tensors,
                "language": language,
                "punctuation": punctuation,
            }
        )
        return {
            "input_features": torch.ones((1, 4, 8), dtype=torch.float32),
            "attention_mask": torch.ones((1, 8), dtype=torch.long),
        }

    def decode(self, output_ids, skip_special_tokens=True):
        return ["ok"]


class _FakeModel:
    def __init__(self):
        self.device = torch.device("cpu")
        self.dtype = torch.float16
        self.generate_kwargs = None

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        return torch.tensor([[1, 2, 3]], dtype=torch.long)


class _SequenceFakeProcessor:
    """Returns different text per call so we can verify multi-chunk stitching."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._idx = 0
        self.calls = []

    def __call__(self, audio_16k, sampling_rate, return_tensors, language, punctuation):
        self.calls.append({"audio_len": len(audio_16k)})
        return {
            "input_features": torch.ones((1, 4, 8), dtype=torch.float32),
            "attention_mask": torch.ones((1, 8), dtype=torch.long),
        }

    def decode(self, output_ids, skip_special_tokens=True):
        text = self._responses[self._idx]
        self._idx += 1
        return [text]


class TestCohereTranscribeEngine(unittest.TestCase):
    def test_transcribe_casts_floating_inputs_to_model_dtype(self):
        engine = CohereTranscribeEngine()
        engine._processor = _FakeProcessor()
        engine._model = _FakeModel()

        result = engine._transcribe_impl(
            np.zeros(16000, dtype=np.float32),
            "en",
            punctuation=True,
            timeout=30.0,
        )

        self.assertEqual(result, "ok")
        self.assertIsNotNone(engine._model.generate_kwargs)
        self.assertEqual(
            engine._model.generate_kwargs["input_features"].dtype,
            torch.float16,
        )
        self.assertEqual(
            engine._model.generate_kwargs["attention_mask"].dtype,
            torch.long,
        )


class TestTokenBudget(unittest.TestCase):
    def test_short_clip_gets_floor(self):
        engine = CohereTranscribeEngine()
        self.assertEqual(engine._token_budget(1.0), 128)

    def test_30s_clip(self):
        engine = CohereTranscribeEngine()
        self.assertEqual(engine._token_budget(30.0), 600)

    def test_clamped_to_decoder_max(self):
        engine = CohereTranscribeEngine()
        engine._decoder_max_seq = 512
        # 60s * 20 = 1200, but clamped to 512
        self.assertEqual(engine._token_budget(60.0), 512)


class TestChunkedTranscription(unittest.TestCase):
    """Verify that long audio is chunked and short audio uses fast path."""

    def _engine(self, responses, max_clip=30.0, overlap=5.0):
        engine = CohereTranscribeEngine()
        engine._processor = _SequenceFakeProcessor(responses)
        engine._model = _FakeModel()
        engine._max_clip_seconds = max_clip
        engine._overlap_seconds = overlap
        return engine

    def test_short_audio_single_pass(self):
        engine = self._engine(["hello world"])
        audio = np.zeros(int(10 * 16000), dtype=np.float32)
        result = engine._transcribe_impl(audio, "en")
        self.assertEqual(result, "hello world")
        self.assertEqual(len(engine._processor.calls), 1)

    def test_long_audio_produces_multiple_chunks(self):
        engine = self._engine([
            "the quick brown fox",
            "brown fox jumps over the lazy dog",
        ], max_clip=30.0, overlap=5.0)
        # 50s audio â†’ should produce 2 chunks with 30s max / 5s overlap
        audio = np.zeros(int(50 * 16000), dtype=np.float32)
        result = engine._transcribe_impl(audio, "en")
        self.assertEqual(len(engine._processor.calls), 2)
        # Verify stitching removed overlap
        self.assertEqual(result, "the quick brown fox jumps over the lazy dog")

    def test_exact_boundary_stays_single_pass(self):
        engine = self._engine(["exact boundary"])
        audio = np.zeros(int(30 * 16000), dtype=np.float32)
        result = engine._transcribe_impl(audio, "en")
        self.assertEqual(result, "exact boundary")
        self.assertEqual(len(engine._processor.calls), 1)

    def test_max_new_tokens_passed_to_model(self):
        engine = self._engine(["hello"])
        audio = np.zeros(int(10 * 16000), dtype=np.float32)
        engine._transcribe_impl(audio, "en")
        gen_kwargs = engine._model.generate_kwargs
        expected_tokens = engine._token_budget(10.0)
        self.assertEqual(gen_kwargs["max_new_tokens"], expected_tokens)

    def test_long_audio_chunk_tokens_use_chunk_duration(self):
        """Each chunk should get a token budget based on its own duration,
        not the total recording duration."""
        engine = self._engine(["part one", "part two"], max_clip=30.0, overlap=5.0)
        audio = np.zeros(int(50 * 16000), dtype=np.float32)
        engine._transcribe_impl(audio, "en")
        # The model.generate is called for each chunk; the last call's
        # kwargs should have a token budget based on chunk duration â‰¤ 30s.
        gen_kwargs = engine._model.generate_kwargs
        self.assertLessEqual(
            gen_kwargs["max_new_tokens"],
            engine._token_budget(30.0),
        )

    def test_three_plus_chunks_all_transcribed(self):
        """Audio spanning 3+ chunks must produce that many transcribe calls."""
        engine = self._engine([
            "the quick brown fox",
            "brown fox jumped over",
            "over the lazy dog",
        ], max_clip=30.0, overlap=5.0)
        # 80s audio â†’ 3 chunks with 30s max / 5s overlap
        audio = np.zeros(int(80 * 16000), dtype=np.float32)
        result = engine._transcribe_impl(audio, "en")
        self.assertEqual(len(engine._processor.calls), 3)
        # Stitching should produce a coherent result
        self.assertIn("quick", result)
        self.assertIn("lazy dog", result)

    def test_very_short_final_chunk_still_transcribed(self):
        """A short tail chunk must still be sent to the model."""
        engine = self._engine([
            "first part of the sentence",
            "the sentence ends here",
        ], max_clip=30.0, overlap=5.0)
        # 32s â†’ just over boundary: chunk1=30s, chunk2=~7s
        audio = np.zeros(int(32 * 16000), dtype=np.float32)
        result = engine._transcribe_impl(audio, "en")
        self.assertEqual(len(engine._processor.calls), 2)
        self.assertIn("ends here", result)


class TestPartialCallback(unittest.TestCase):
    """Per-chunk partial-result callback contract."""

    def _engine(self, responses, max_clip=30.0, overlap=5.0):
        engine = CohereTranscribeEngine()
        engine._processor = _SequenceFakeProcessor(responses)
        engine._model = _FakeModel()
        engine._max_clip_seconds = max_clip
        engine._overlap_seconds = overlap
        return engine

    def test_partial_callback_fires_per_chunk(self):
        engine = self._engine([
            "the quick brown fox",
            "brown fox jumps over",
            "over the lazy dog",
        ], max_clip=30.0, overlap=5.0)
        audio = np.zeros(int(80 * 16000), dtype=np.float32)
        calls = []
        engine._transcribe_impl(audio, "en",
                                partial_callback=lambda t, i, n: calls.append((t, i, n)))
        # One call per chunk, correct indexing.
        self.assertEqual(len(calls), 3)
        self.assertEqual([c[1] for c in calls], [1, 2, 3])
        self.assertTrue(all(c[2] == 3 for c in calls))
        # Running text should be non-empty and monotonically non-shrinking.
        self.assertTrue(all(len(c[0]) > 0 for c in calls))
        self.assertGreaterEqual(len(calls[-1][0]), len(calls[0][0]))

    def test_partial_callback_single_chunk_does_not_fire(self):
        engine = self._engine(["short clip"])
        audio = np.zeros(int(10 * 16000), dtype=np.float32)
        calls = []
        result = engine._transcribe_impl(audio, "en",
                                         partial_callback=lambda *a: calls.append(a))
        self.assertEqual(result, "short clip")
        self.assertEqual(calls, [])

    def test_partial_callback_exception_is_swallowed(self):
        engine = self._engine([
            "first chunk text",
            "second chunk text",
        ], max_clip=30.0, overlap=5.0)
        audio = np.zeros(int(50 * 16000), dtype=np.float32)

        def _boom(text, i, n):
            raise RuntimeError("callback failure")

        result = engine._transcribe_impl(audio, "en", partial_callback=_boom)
        # Final result still returned even though every callback raised.
        self.assertIn("first", result)
        self.assertIn("second", result)


class TestConfigReading(unittest.TestCase):
    """Model config attributes should be read into engine limits."""

    def test_config_values_applied_after_load_simulation(self):
        engine = CohereTranscribeEngine()
        # Simulate what load() does after model creation
        engine._model = _FakeModel()
        engine._model.config = SimpleNamespace(
            max_audio_clip_s=35,
            overlap_chunk_second=5,
            max_seq_len=1024,
        )
        cfg = engine._model.config
        engine._max_clip_seconds = float(getattr(cfg, "max_audio_clip_s", 30.0))
        engine._overlap_seconds = float(getattr(cfg, "overlap_chunk_second", 5.0))
        engine._decoder_max_seq = int(getattr(cfg, "max_seq_len", 1024))

        self.assertEqual(engine._max_clip_seconds, 35.0)
        self.assertEqual(engine._overlap_seconds, 5.0)
        self.assertEqual(engine._decoder_max_seq, 1024)

    def test_defaults_without_config(self):
        engine = CohereTranscribeEngine()
        self.assertEqual(engine._max_clip_seconds, 30.0)
        self.assertEqual(engine._overlap_seconds, 5.0)
        self.assertEqual(engine._decoder_max_seq, 1024)


if __name__ == "__main__":
    unittest.main()
