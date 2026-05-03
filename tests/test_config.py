import json
import tempfile
import unittest
from pathlib import Path

from speakeasy.config import Settings


class SettingsConfigTests(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "settings.json"
            models_dir = Path(temp_dir) / "models"
            models_dir.mkdir()

            settings = Settings(
                engine="granite",
                model_path=str(models_dir),
                device="cpu",
                speech_task="translate",
                translation_target_language="French",
                keyword_bias="Granite, PX-42",
                formatting_style="preserve_spoken_wording",
                auto_copy=False,
                punctuation=False,
            )
            settings.save(config_path)

            loaded = Settings.load(config_path)

            self.assertEqual(loaded.engine, "granite")
            self.assertEqual(loaded.speech_task, "translate")
            self.assertEqual(loaded.translation_target_language, "French")
            self.assertEqual(loaded.keyword_bias, "Granite, PX-42")
            self.assertEqual(loaded.formatting_style, "preserve_spoken_wording")
            self.assertFalse(loaded.punctuation)
            self.assertEqual(loaded.model_path, str(models_dir))
            self.assertEqual(loaded.device, "cpu")
            self.assertFalse(loaded.auto_copy)

    def test_load_ignores_unknown_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "settings.json"
            config_path.write_text(
                json.dumps(
                    {
                        "engine": "granite",
                        "language": "en",
                        "unexpected": "ignore-me",
                    }
                ),
                encoding="utf-8",
            )

            loaded = Settings.load(config_path)

            self.assertEqual(loaded.engine, "granite")
            self.assertEqual(loaded.language, "en")
            self.assertFalse(hasattr(loaded, "unexpected"))

    def test_defaults(self):
        s = Settings()
        self.assertEqual(s.engine, "granite")
        self.assertEqual(s.speech_task, "transcribe")
        self.assertEqual(s.translation_target_language, "English")
        self.assertEqual(s.keyword_bias, "")
        self.assertEqual(s.formatting_style, "sentence_case")
        self.assertEqual(s.device, "cuda")
        self.assertEqual(s.sample_rate, 16000)
        self.assertTrue(s.auto_copy)
        self.assertTrue(s.auto_paste)
        self.assertTrue(s.hotkeys_enabled)
        self.assertTrue(s.punctuation)
        # Streaming partial transcription defaults to on.
        self.assertTrue(s.streaming_partials_enabled)
        # Professional Mode defaults
        self.assertFalse(s.professional_mode)
        self.assertEqual(s.pro_active_preset, "General Professional")
        self.assertFalse(s.store_api_key)

    def test_streaming_partials_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "settings.json"
            settings = Settings(streaming_partials_enabled=False)
            settings.save(config_path)
            loaded = Settings.load(config_path)
            self.assertFalse(loaded.streaming_partials_enabled)

    def test_load_missing_file_returns_defaults(self):
        loaded = Settings.load(Path("/nonexistent/path/settings.json"))
        self.assertEqual(loaded.engine, "granite")

    def test_load_corrupt_json_returns_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "settings.json"
            config_path.write_text("not valid json {{{", encoding="utf-8")
            loaded = Settings.load(config_path)
            self.assertEqual(loaded.engine, "granite")

    def test_professional_mode_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "settings.json"

            settings = Settings(
                professional_mode=True,
                pro_active_preset="Technical / Engineering",
                store_api_key=True,
            )
            settings.save(config_path)
            loaded = Settings.load(config_path)

            self.assertTrue(loaded.professional_mode)
            self.assertEqual(loaded.pro_active_preset, "Technical / Engineering")
            self.assertTrue(loaded.store_api_key)

    def test_api_key_never_in_settings_json(self):
        """The actual API key value must NEVER be serialised into settings.json."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "settings.json"
            settings = Settings(professional_mode=True, store_api_key=True)
            settings.save(config_path)
            raw = config_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            # store_api_key (bool preference) is allowed, but there must be
            # no field that could hold an actual API key string value.
            self.assertNotIn("openai_api_key", data)
            self.assertNotIn("api_key", data)        # no bare 'api_key' field
            self.assertNotIn("openai", raw.lower().replace("store_api_key", ""))
            # Verify no string value looks like an API key
            for v in data.values():
                if isinstance(v, str):
                    self.assertFalse(
                        v.startswith("sk-"),
                        "A value resembling an API key was found in settings JSON",
                    )


if __name__ == "__main__":
    unittest.main()


class SettingsValidationTests(unittest.TestCase):
    """Tests for Settings.validate() correcting invalid values."""

    def test_invalid_engine_falls_back_to_granite(self):
        s = Settings(engine="nonexistent")
        s.validate()
        self.assertEqual(s.engine, "granite")

    def test_valid_engines_accepted(self):
        for engine in ("granite",):
            s = Settings(engine=engine)
            s.validate()
            self.assertEqual(s.engine, engine)

    def test_invalid_device_falls_back_to_cuda(self):
        s = Settings(device="gpu")
        s.validate()
        self.assertEqual(s.device, "cuda")

    def test_valid_devices_accepted(self):
        for device in ("cuda", "cpu"):
            s = Settings(device=device)
            s.validate()
            self.assertEqual(s.device, device)

    def test_sample_rate_too_low_reset(self):
        s = Settings(sample_rate=100)
        s.validate()
        self.assertEqual(s.sample_rate, 16000)

    def test_sample_rate_too_high_reset(self):
        s = Settings(sample_rate=96000)
        s.validate()
        self.assertEqual(s.sample_rate, 16000)

    def test_valid_sample_rate_unchanged(self):
        for sr in (8000, 16000, 44100, 48000):
            s = Settings(sample_rate=sr)
            s.validate()
            self.assertEqual(s.sample_rate, sr)

    def test_inference_timeout_too_low_reset(self):
        s = Settings(inference_timeout=0)
        s.validate()
        self.assertEqual(s.inference_timeout, 30)

    def test_silence_threshold_zero_reset(self):
        s = Settings(silence_threshold=0)
        s.validate()
        self.assertEqual(s.silence_threshold, 0.0015)

    def test_load_invalid_engine_in_json_corrected(self):
        """Settings loaded from JSON with invalid engine should be corrected."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "settings.json"
            p.write_text(json.dumps({"engine": "invalid_eng"}), encoding="utf-8")
            s = Settings.load(p)
            self.assertEqual(s.engine, "granite")

    def test_invalid_speech_task_falls_back_to_transcribe(self):
        s = Settings(speech_task="summarize")
        s.validate()
        self.assertEqual(s.speech_task, "transcribe")

    def test_auto_language_is_valid(self):
        s = Settings(language="auto")
        s.validate()
        self.assertEqual(s.language, "auto")

    def test_invalid_language_falls_back_to_english_code(self):
        s = Settings(language="xx")
        s.validate()
        self.assertEqual(s.language, "en")

    def test_invalid_translation_target_falls_back_to_english(self):
        s = Settings(translation_target_language="Portuguese")
        s.validate()
        self.assertEqual(s.translation_target_language, "English")

    def test_invalid_formatting_style_falls_back_to_sentence_case(self):
        s = Settings(formatting_style="meeting_notes")
        s.validate()
        self.assertEqual(s.formatting_style, "sentence_case")

