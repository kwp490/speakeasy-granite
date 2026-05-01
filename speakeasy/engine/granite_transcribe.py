"""
IBM Granite Speech 4.1 engine.

Uses the ``AutoModelForSpeechSeq2Seq`` model from HuggingFace transformers for
local speech recognition and speech translation.

Model: ibm-granite/granite-speech-4.1-2b
"""

from __future__ import annotations

import logging
import os

import numpy as np

from .base import SpeechEngine

log = logging.getLogger(__name__)

GRANITE_REPO_ID = "ibm-granite/granite-speech-4.1-2b"


class GraniteTranscribeEngine(SpeechEngine):
    """IBM Granite Speech 4.1 2B ASR/AST model."""

    def __init__(self) -> None:
        super().__init__()
        self._processor = None
        self._tokenizer = None
        self._total_tokens: int = 0
        self._total_audio_sec: float = 0.0
        self._last_tok_per_sec: float = 0.0
        self._last_realtime_factor: float = 0.0
        self._last_inference_time: float = 0.0
        self._device: str = "cpu"
        self._actual_device: str = "cpu"
        self._inference_seq: int = 0
        self._speech_task: str = "transcribe"
        self._translation_target_language: str = "English"
        self._keyword_bias: str = ""

    @property
    def name(self) -> str:
        return "granite"

    @property
    def vram_estimate_gb(self) -> float:
        return 6.0

    @property
    def actual_device(self) -> str:
        return self._actual_device

    def configure_prompt_options(
        self,
        *,
        speech_task: str = "transcribe",
        translation_target_language: str = "English",
        keyword_bias: str = "",
    ) -> None:
        """Set Granite prompt options for the next transcription call."""
        self._speech_task = speech_task if speech_task in {"transcribe", "translate"} else "transcribe"
        self._translation_target_language = translation_target_language or "English"
        self._keyword_bias = keyword_bias.strip()

    def load(self, model_path: str, device: str = "cuda") -> None:
        import torch
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

        self._device = device
        granite_dir = os.path.join(model_path, "granite")

        if not os.path.isdir(granite_dir) or not os.path.isfile(
            os.path.join(granite_dir, "config.json")
        ):
            log.info("Granite model not found at %s; downloading", granite_dir)
            from speakeasy.model_downloader import (
                EXIT_AUTH_REQUIRED,
                EXIT_SUCCESS,
                download_model,
            )

            rc = download_model("granite", model_path)
            if rc == EXIT_AUTH_REQUIRED:
                raise RuntimeError(
                    "The IBM Granite Speech model requires HuggingFace authentication. "
                    f"Please provide a token with access to {GRANITE_REPO_ID}."
                )
            if rc != EXIT_SUCCESS:
                raise RuntimeError(f"Failed to download Granite model from {GRANITE_REPO_ID}.")

        log.info("Loading IBM Granite Speech from %s", granite_dir)

        self._processor = AutoProcessor.from_pretrained(granite_dir)
        self._tokenizer = self._processor.tokenizer
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        self._model = AutoModelForSpeechSeq2Seq.from_pretrained(
            granite_dir,
            device_map=device if device == "cuda" else "cpu",
            torch_dtype=dtype,
        )
        self._actual_device = self._infer_model_device(device)

        cfg = getattr(self._model, "config", None)
        if cfg is not None:
            self._max_clip_seconds = float(
                getattr(cfg, "max_audio_clip_s", self._max_clip_seconds)
            )
            self._overlap_seconds = float(
                getattr(cfg, "overlap_chunk_second", self._overlap_seconds)
            )
            self._decoder_max_seq = int(
                getattr(cfg, "max_seq_len", self._decoder_max_seq)
            )
        log.info(
            "Granite Speech loaded on %s; max_clip=%.0fs overlap=%.0fs decoder_max_seq=%d",
            self._actual_device,
            self._max_clip_seconds,
            self._overlap_seconds,
            self._decoder_max_seq,
        )

    _max_clip_seconds: float = 30.0
    _overlap_seconds: float = 5.0
    _decoder_max_seq: int = 1024

    def _infer_model_device(self, requested_device: str) -> str:
        try:
            model_device = next(self._model.parameters()).device
        except (AttributeError, StopIteration):
            model_device = getattr(self._model, "device", requested_device)
        model_device_text = str(model_device).lower()
        return "cuda" if model_device_text.startswith("cuda") else "cpu"

    def _token_budget(self, clip_duration_sec: float) -> int:
        budget = max(64, int(clip_duration_sec * 12))
        return min(budget, self._decoder_max_seq)

    @property
    def token_stats(self) -> tuple[float, int, float, float, int]:
        return (
            self._last_tok_per_sec,
            self._total_tokens,
            self._total_audio_sec,
            self._last_realtime_factor,
            self._inference_seq,
        )

    def _transcribe_impl(
        self,
        audio_16k: np.ndarray,
        language: str,
        punctuation: bool = True,
        timeout: float = 30.0,
        partial_callback=None,
    ) -> str:
        from .audio_utils import chunk_audio, stitch_transcripts
        import time as _time

        duration_sec = len(audio_16k) / 16000
        self._total_audio_sec += duration_sec
        impl_start = _time.monotonic()

        if duration_sec <= self._max_clip_seconds:
            result = self._transcribe_chunk(
                audio_16k,
                language,
                punctuation,
                timeout,
                self._token_budget(duration_sec),
            )
            wall = _time.monotonic() - impl_start
            if wall > 0:
                self._last_realtime_factor = duration_sec / wall
            return result

        chunks = chunk_audio(
            audio_16k,
            sr=16000,
            max_seconds=self._max_clip_seconds,
            overlap_seconds=self._overlap_seconds,
        )
        texts = []
        total = len(chunks)
        for index, chunk in enumerate(chunks):
            chunk_duration = len(chunk) / 16000
            text = self._transcribe_chunk(
                chunk,
                language,
                punctuation,
                timeout,
                self._token_budget(chunk_duration),
            )
            texts.append(text)
            if partial_callback is not None:
                try:
                    partial_callback(stitch_transcripts(texts), index + 1, total)
                except Exception:
                    log.exception("partial_callback raised; ignoring")

        result = stitch_transcripts(texts)
        wall = _time.monotonic() - impl_start
        if wall > 0:
            self._last_realtime_factor = duration_sec / wall
        return result

    def _build_user_prompt(self, language: str, punctuation: bool) -> str:
        keywords = self._normalized_keywords()
        if self._speech_task == "translate":
            prompt = f"translate the speech to {self._translation_target_language}"
            if punctuation:
                prompt += " with proper punctuation and capitalization"
            prompt += "."
        elif keywords:
            prompt = "transcribe the speech to text."
        elif punctuation:
            prompt = "transcribe the speech with proper punctuation and capitalization."
        else:
            prompt = "can you transcribe the speech into a written format?"

        if keywords:
            prompt += f" Keywords: {keywords}"
        return prompt

    def _normalized_keywords(self) -> str:
        parts = [part.strip() for part in self._keyword_bias.replace("\n", ",").split(",")]
        return ", ".join(part for part in parts if part)

    def _transcribe_chunk(
        self,
        audio_16k: np.ndarray,
        language: str,
        punctuation: bool,
        timeout: float,
        max_new_tokens: int,
    ) -> str:
        import time as _time

        import torch
        from transformers.generation.stopping_criteria import (
            MaxTimeCriteria,
            StoppingCriteriaList,
        )

        user_prompt = f"<|audio|>{self._build_user_prompt(language, punctuation)}"
        chat = [{"role": "user", "content": user_prompt}]
        prompt = self._tokenizer.apply_chat_template(
            chat,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self._processor(
            prompt,
            audio_16k,
            device=self._actual_device,
            return_tensors="pt",
        )
        inputs = self._move_inputs_to_model(inputs)
        input_token_count = inputs["input_ids"].shape[-1]
        stopping = StoppingCriteriaList([MaxTimeCriteria(max_time=timeout)])

        start = _time.monotonic()
        with torch.no_grad():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                num_beams=1,
                stopping_criteria=stopping,
            )

        new_tokens = output_ids[0, input_token_count:].unsqueeze(0)
        elapsed = _time.monotonic() - start
        generated_token_count = int(new_tokens.shape[-1])
        self._total_tokens += generated_token_count
        if elapsed > 0:
            self._last_tok_per_sec = generated_token_count / elapsed
        self._last_inference_time = _time.monotonic()
        self._inference_seq += 1

        text = self._tokenizer.batch_decode(
            new_tokens,
            add_special_tokens=False,
            skip_special_tokens=True,
        )
        if isinstance(text, (list, tuple)):
            text = text[0] if text else ""
        return str(text).strip()

    def _move_inputs_to_model(self, inputs):
        import torch

        if hasattr(inputs, "to"):
            try:
                return inputs.to(self._actual_device)
            except TypeError:
                pass

        model_dtype = getattr(self._model, "dtype", None)
        if model_dtype is None:
            try:
                model_dtype = next(self._model.parameters()).dtype
            except (AttributeError, StopIteration):
                model_dtype = None

        converted_inputs = {}
        for key, value in inputs.items():
            if not hasattr(value, "to"):
                converted_inputs[key] = value
                continue
            tensor = value.to(self._actual_device)
            if model_dtype is not None and torch.is_floating_point(tensor):
                tensor = tensor.to(dtype=model_dtype)
            converted_inputs[key] = tensor
        return converted_inputs

    def unload(self) -> None:
        self._processor = None
        self._tokenizer = None
        self._release_model()