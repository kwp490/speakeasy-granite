"""Targeted tests for the IBM Granite transcription engine."""

import unittest

import numpy as np
import torch

from speakeasy.engine.granite_transcribe import GraniteTranscribeEngine


class _FakeTokenizer:
    def __init__(self, responses=None):
        self.responses = list(responses or ["ok"])
        self.chats = []
        self.decoded_tokens = []

    def apply_chat_template(self, chat, tokenize=False, add_generation_prompt=True):
        self.chats.append(chat)
        return "chat prompt"

    def batch_decode(self, tokens, add_special_tokens=False, skip_special_tokens=True):
        self.decoded_tokens.append(tokens.clone())
        return [self.responses.pop(0)]


class _FakeProcessor:
    def __init__(self, responses=None):
        self.tokenizer = _FakeTokenizer(responses)
        self.calls = []

    def __call__(self, prompt, audio_16k, device, return_tensors):
        self.calls.append(
            {
                "prompt": prompt,
                "audio_len": len(audio_16k),
                "device": device,
                "return_tensors": return_tensors,
            }
        )
        return {
            "input_ids": torch.tensor([[10, 11]], dtype=torch.long),
            "input_features": torch.ones((1, 4, 8), dtype=torch.float32),
        }


class _FakeModel:
    def __init__(self):
        self.device = torch.device("cpu")
        self.dtype = torch.float16
        self.generate_kwargs = None

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        return torch.tensor([[10, 11, 21, 22]], dtype=torch.long)


class TestGranitePrompting(unittest.TestCase):
    def _engine(self, responses=None):
        engine = GraniteTranscribeEngine()
        engine._processor = _FakeProcessor(responses)
        engine._tokenizer = engine._processor.tokenizer
        engine._model = _FakeModel()
        engine._actual_device = "cpu"
        return engine

    def test_transcribe_prompt_uses_audio_marker_and_punctuation(self):
        engine = self._engine(["hello"])
        result = engine._transcribe_impl(np.zeros(16000, dtype=np.float32), "en")

        self.assertEqual(result, "hello")
        content = engine._tokenizer.chats[0][0]["content"]
        self.assertIn("<|audio|>", content)
        self.assertIn("proper punctuation and capitalization", content)

    def test_punctuation_off_uses_basic_transcription_prompt(self):
        engine = self._engine(["hello"])
        engine.configure_prompt_options(formatting_style="preserve_spoken_wording")

        engine._transcribe_impl(np.zeros(16000, dtype=np.float32), "en", punctuation=False)

        content = engine._tokenizer.chats[0][0]["content"]
        self.assertIn("<|audio|>can you transcribe the speech into a written format?", content)
        self.assertNotIn("proper punctuation and capitalization", content)

    def test_plain_text_formatting_prompt(self):
        engine = self._engine(["hello"])
        engine.configure_prompt_options(formatting_style="plain_text")

        engine._transcribe_impl(np.zeros(16000, dtype=np.float32), "en")

        content = engine._tokenizer.chats[0][0]["content"]
        self.assertIn("Transcribe the speech as plain text.", content)

    def test_preserve_spoken_wording_formatting_prompt(self):
        engine = self._engine(["hello"])
        engine.configure_prompt_options(formatting_style="preserve_spoken_wording")

        engine._transcribe_impl(np.zeros(16000, dtype=np.float32), "en")

        content = engine._tokenizer.chats[0][0]["content"]
        self.assertIn(
            "Transcribe exactly what is spoken, preserving wording, "
            "with proper punctuation and capitalization.",
            content,
        )

    def test_translate_prompt_uses_target_language(self):
        engine = self._engine(["bonjour"])
        engine.configure_prompt_options(
            speech_task="translate",
            translation_target_language="French",
        )

        engine._transcribe_impl(np.zeros(16000, dtype=np.float32), "en")

        content = engine._tokenizer.chats[0][0]["content"]
        self.assertIn("translate the speech to French with proper punctuation and capitalization.", content)

    def test_translate_prompt_can_omit_punctuation_clause(self):
        engine = self._engine(["bonjour"])
        engine.configure_prompt_options(
            speech_task="translate",
            translation_target_language="French",
        )

        engine._transcribe_impl(np.zeros(16000, dtype=np.float32), "en", punctuation=False)

        content = engine._tokenizer.chats[0][0]["content"]
        self.assertIn("translate the speech to French.", content)
        self.assertNotIn("proper punctuation and capitalization", content)

    def test_keyword_bias_prompt_is_normalized(self):
        engine = self._engine(["acme rocket"])
        engine.configure_prompt_options(keyword_bias="Acme,  PX-42\nGranite")

        engine._transcribe_impl(np.zeros(16000, dtype=np.float32), "en")

        content = engine._tokenizer.chats[0][0]["content"]
        self.assertIn("transcribe the speech with proper punctuation and capitalization.", content)
        self.assertIn("Keywords: Acme, PX-42, Granite", content)

    def test_only_new_tokens_are_decoded(self):
        engine = self._engine(["decoded"])
        engine._transcribe_impl(np.zeros(16000, dtype=np.float32), "en")

        decoded = engine._tokenizer.decoded_tokens[0]
        self.assertEqual(decoded.tolist(), [[21, 22]])

    def test_floating_inputs_cast_to_model_dtype(self):
        engine = self._engine(["ok"])
        engine._transcribe_impl(np.zeros(16000, dtype=np.float32), "en")

        self.assertEqual(engine._model.generate_kwargs["input_features"].dtype, torch.float16)
        self.assertEqual(engine._model.generate_kwargs["input_ids"].dtype, torch.long)


class TestGraniteChunking(unittest.TestCase):
    def _engine(self, responses, max_clip=30.0, overlap=5.0):
        engine = GraniteTranscribeEngine()
        engine._processor = _FakeProcessor(responses)
        engine._tokenizer = engine._processor.tokenizer
        engine._model = _FakeModel()
        engine._actual_device = "cpu"
        engine._max_clip_seconds = max_clip
        engine._overlap_seconds = overlap
        return engine

    def test_short_audio_single_pass(self):
        engine = self._engine(["short clip"])
        result = engine._transcribe_impl(np.zeros(int(10 * 16000), dtype=np.float32), "en")
        self.assertEqual(result, "short clip")
        self.assertEqual(len(engine._processor.calls), 1)

    def test_long_audio_chunks_and_stitches_final_result(self):
        engine = self._engine(
            ["the quick brown fox", "brown fox jumps over"],
            max_clip=30.0,
            overlap=5.0,
        )
        result = engine._transcribe_impl(
            np.zeros(int(50 * 16000), dtype=np.float32),
            "en",
        )

        self.assertEqual(len(engine._processor.calls), 2)
        self.assertEqual(result, "the quick brown fox jumps over")


class TestGraniteTokenBudget(unittest.TestCase):
    def test_short_clip_gets_floor(self):
        engine = GraniteTranscribeEngine()
        self.assertEqual(engine._token_budget(1.0), 64)

    def test_clamped_to_decoder_max(self):
        engine = GraniteTranscribeEngine()
        engine._decoder_max_seq = 128
        self.assertEqual(engine._token_budget(60.0), 128)


if __name__ == "__main__":
    unittest.main()