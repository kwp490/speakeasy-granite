"""Tests for engine audio utilities â€” chunking, stitching, resampling."""

import unittest

import numpy as np

from speakeasy.engine.audio_utils import (
    chunk_audio,
    ensure_16khz,
    stitch_transcripts,
)


class TestChunkAudio(unittest.TestCase):
    """chunk_audio: boundary conditions, overlap, and parameter validation."""

    def _audio(self, seconds: float, sr: int = 16000) -> np.ndarray:
        return np.zeros(int(seconds * sr), dtype=np.float32)

    def test_short_audio_returns_single_chunk(self):
        audio = self._audio(10.0)
        chunks = chunk_audio(audio, sr=16000, max_seconds=30.0, overlap_seconds=5.0)
        self.assertEqual(len(chunks), 1)
        self.assertIs(chunks[0], audio)

    def test_exact_boundary_returns_single_chunk(self):
        audio = self._audio(30.0)
        chunks = chunk_audio(audio, sr=16000, max_seconds=30.0, overlap_seconds=5.0)
        self.assertEqual(len(chunks), 1)

    def test_just_over_boundary_returns_two_chunks(self):
        audio = self._audio(30.1)
        chunks = chunk_audio(audio, sr=16000, max_seconds=30.0, overlap_seconds=5.0)
        self.assertEqual(len(chunks), 2)

    def test_chunks_cover_all_audio(self):
        """Every sample must appear in at least one chunk."""
        audio = np.arange(100 * 16000, dtype=np.float32)  # 100 s
        chunks = chunk_audio(audio, sr=16000, max_seconds=30.0, overlap_seconds=5.0)
        # First sample of first chunk
        self.assertEqual(chunks[0][0], 0.0)
        # Last sample of last chunk
        self.assertEqual(chunks[-1][-1], audio[-1])

    def test_chunk_max_length_respected(self):
        audio = self._audio(120.0)
        chunks = chunk_audio(audio, sr=16000, max_seconds=35.0, overlap_seconds=5.0)
        max_samples = int(35.0 * 16000)
        for c in chunks:
            self.assertLessEqual(len(c), max_samples)

    def test_overlap_produces_shared_samples(self):
        audio = np.arange(70 * 16000, dtype=np.float32)
        chunks = chunk_audio(audio, sr=16000, max_seconds=35.0, overlap_seconds=5.0)
        self.assertGreaterEqual(len(chunks), 2)
        # End of chunk 0 should share samples with start of chunk 1
        overlap_samples = int(5.0 * 16000)
        np.testing.assert_array_equal(
            chunks[0][-overlap_samples:],
            chunks[1][:overlap_samples],
        )

    def test_overlap_ge_max_raises(self):
        audio = self._audio(60.0)
        with self.assertRaises(ValueError):
            chunk_audio(audio, sr=16000, max_seconds=10.0, overlap_seconds=10.0)

    def test_very_short_final_chunk(self):
        """A recording just past a boundary should produce a short tail chunk."""
        # 52s with 30s max / 5s overlap â†’ chunk1: 0-30s, chunk2: 25-52s (27s)
        audio = self._audio(52.0)
        chunks = chunk_audio(audio, sr=16000, max_seconds=30.0, overlap_seconds=5.0)
        self.assertEqual(len(chunks), 2)
        # Last chunk is shorter than max
        self.assertLess(len(chunks[-1]), int(30.0 * 16000))
        self.assertGreater(len(chunks[-1]), 0)

    def test_many_chunks_short_tail(self):
        """100s audio: last chunk should be short but non-empty."""
        audio = self._audio(100.0)
        chunks = chunk_audio(audio, sr=16000, max_seconds=30.0, overlap_seconds=5.0)
        self.assertGreater(len(chunks), 3)
        # Every chunk is non-empty
        for c in chunks:
            self.assertGreater(len(c), 0)
        # Last chunk covers the final sample
        self.assertEqual(chunks[-1][-1], audio[-1])

    def test_empty_audio(self):
        audio = np.array([], dtype=np.float32)
        chunks = chunk_audio(audio, sr=16000, max_seconds=30.0, overlap_seconds=5.0)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 0)


class TestStitchTranscripts(unittest.TestCase):
    """stitch_transcripts: overlap dedup, punctuation, edge cases."""

    def test_empty_list(self):
        self.assertEqual(stitch_transcripts([]), "")

    def test_single_text(self):
        self.assertEqual(stitch_transcripts(["hello world"]), "hello world")

    def test_no_overlap_concatenates(self):
        result = stitch_transcripts(["the cat sat", "on the mat"])
        self.assertEqual(result, "the cat sat on the mat")

    def test_exact_word_overlap(self):
        result = stitch_transcripts([
            "the quick brown fox",
            "brown fox jumps over",
        ])
        self.assertEqual(result, "the quick brown fox jumps over")

    def test_case_insensitive_overlap(self):
        result = stitch_transcripts([
            "The Quick Brown Fox",
            "brown fox jumps over",
        ])
        # Next chunk's version (lower-case) wins in the overlap region.
        self.assertEqual(result, "The Quick brown fox jumps over")

    def test_punctuation_insensitive_overlap(self):
        result = stitch_transcripts([
            "the quick brown fox.",
            "brown fox jumps over",
        ])
        self.assertEqual(result, "the quick brown fox jumps over")

    def test_trailing_comma_overlap(self):
        result = stitch_transcripts([
            "hello world, I said",
            "I said goodbye",
        ])
        self.assertEqual(result, "hello world, I said goodbye")

    def test_skip_empty_chunks(self):
        result = stitch_transcripts(["hello", "", "world"])
        self.assertEqual(result, "hello world")

    def test_three_chunks_with_overlap(self):
        result = stitch_transcripts([
            "one two three four",
            "three four five six",
            "five six seven eight",
        ])
        self.assertEqual(result, "one two three four five six seven eight")

    def test_max_overlap_words_respected(self):
        """When max_overlap_words is too small, overlap is not detected."""
        result = stitch_transcripts(
            ["a b c d e f g h i j k l m", "j k l m n o"],
            max_overlap_words=3,  # too small to find 4-word overlap
        )
        # Falls back to concatenation
        self.assertIn("j k l m n o", result)
        # With sufficient window, dedup works
        result2 = stitch_transcripts(
            ["a b c d e f g h i j k l m", "j k l m n o"],
            max_overlap_words=25,
        )
        self.assertEqual(result2, "a b c d e f g h i j k l m n o")

    def test_all_empty(self):
        self.assertEqual(stitch_transcripts(["", "", ""]), "")

    def test_repeated_phrase_picks_longest_overlap(self):
        """When 'the the' appears, pick the longest valid overlap."""
        result = stitch_transcripts([
            "I said the the end",
            "the end is near",
        ])
        self.assertEqual(result, "I said the the end is near")


class TestEnsure16khz(unittest.TestCase):
    def test_already_16khz_passthrough(self):
        audio = np.ones(16000, dtype=np.float32)
        result = ensure_16khz(audio, 16000)
        self.assertIs(result, audio)

    def test_downsample_48k(self):
        audio = np.ones(48000, dtype=np.float32)
        result = ensure_16khz(audio, 48000)
        self.assertEqual(len(result), 16000)

    def test_empty_audio(self):
        audio = np.array([], dtype=np.float32)
        result = ensure_16khz(audio, 44100)
        self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main()

