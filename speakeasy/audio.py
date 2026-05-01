"""
Audio recording and silence trimming.

Wraps sounddevice InputStream with queue-based buffering, RMS silence gate,
and in-memory WAV encoding.
"""

from __future__ import annotations

import io
import logging
import queue
import sys
import threading
import time
from typing import List, Optional, Tuple

import numpy as np
import sounddevice as sd
import soundfile as sf

log = logging.getLogger(__name__)


class AudioRecorder:
    """Captures microphone audio into a thread-safe queue."""

    def __init__(
        self,
        sample_rate: int = 16000,
        silence_threshold: float = 0.0015,
        silence_margin_ms: int = 500,
        device: Optional[int] = None,
    ):
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold
        self.silence_margin = int(sample_rate * silence_margin_ms / 1000)
        self.device = device

        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._recording = threading.Event()
        self._stream: Optional[sd.InputStream] = None
        self._last_callback_time: float = 0.0
        self._recovery_count: int = 0
        self._max_recoveries: int = 3

    # ── Stream lifecycle ─────────────────────────────────────────────────────

    def open_stream(self) -> None:
        """Open and start the persistent microphone stream."""
        self._last_callback_time = 0.0
        dev = self.device if self.device is not None and self.device >= 0 else None
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            callback=self._callback,
            dtype="float32",
            device=dev,
        )
        self._stream.start()
        log.info(
            "Audio stream opened (device=%s, sr=%d)",
            dev if dev is not None else "default",
            self.sample_rate,
        )

    def close_stream(self) -> None:
        """Stop and close the microphone stream."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                log.warning("Error closing audio stream", exc_info=True)
            self._stream = None
            log.info("Audio stream closed")

    # ── Stream health ────────────────────────────────────────────────────────

    def stream_is_alive(self, timeout: float = 0.5) -> bool:
        """Return True if the PortAudio callback has fired recently."""
        if self._stream is None:
            return False
        if self._last_callback_time == 0.0:
            return False
        return (time.monotonic() - self._last_callback_time) < timeout

    def recover_stream(self) -> bool:
        """Close and re-open the stream to recover from a stale state.

        Returns True if the stream is alive after recovery.
        """
        if self._recovery_count >= self._max_recoveries:
            log.error(
                "Audio recovery limit reached (%d attempts) — "
                "microphone may be unavailable",
                self._max_recoveries,
            )
            return False
        self._recovery_count += 1
        log.warning(
            "Attempting audio stream recovery (attempt %d/%d)",
            self._recovery_count,
            self._max_recoveries,
        )
        self.close_stream()
        try:
            self.open_stream()
        except Exception:
            log.error("Audio stream recovery failed", exc_info=True)
            return False
        # Give PortAudio time to deliver the first callback
        time.sleep(0.3)
        alive = self.stream_is_alive()
        if alive:
            log.info("Audio stream recovery succeeded")
            self._recovery_count = 0  # reset on success
        else:
            log.warning("Audio stream recovery did not restore callback")
        return alive

    def reset_recovery_count(self) -> None:
        """Reset the consecutive recovery counter (call after successful recording)."""
        self._recovery_count = 0

    # ── Recording control ────────────────────────────────────────────────────

    def start_recording(self) -> None:
        """Begin capturing audio frames into the queue."""
        # Drain stale frames
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._recording.set()
        log.debug("Recording started")

    def stop_recording(self) -> Optional[np.ndarray]:
        """Stop capturing and return the concatenated audio (or None if empty)."""
        self._recording.clear()
        frames: List[np.ndarray] = []
        while not self._queue.empty():
            try:
                frames.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if not frames:
            log.warning("No audio frames captured")
            return None
        audio = np.concatenate(frames, axis=0)
        log.debug("Recording stopped: %.2fs captured", len(audio) / self.sample_rate)
        return audio

    def get_raw_audio(self) -> Optional[np.ndarray]:
        """Return recorded audio as 1D float32 mono array (samples,)."""
        audio = self.stop_recording()
        if audio is None:
            return None
        # Downmix to mono if multi-channel, then flatten to 1D
        if audio.ndim == 2:
            if audio.shape[1] > 1:
                audio = np.mean(audio, axis=1)  # multi-channel → mono
            else:
                audio = audio[:, 0]  # single-channel (samples,1) → (samples,)
        return audio.astype(np.float32)

    @property
    def is_recording(self) -> bool:
        return self._recording.is_set()

    # ── Silence trimming ─────────────────────────────────────────────────────

    def trim_silence(self, audio: np.ndarray) -> Optional[Tuple[np.ndarray, float]]:
        """Trim leading/trailing silence.  Returns (trimmed_audio, pct_trimmed)."""
        mono = audio[:, 0] if audio.ndim == 2 else audio
        win = int(self.sample_rate * 0.02)  # 20 ms windows
        if len(mono) < win:
            return audio, 0.0

        energy = np.array(
            [
                np.sqrt(np.mean(mono[i : i + win] ** 2))
                for i in range(0, len(mono) - win, win)
            ]
        )
        voiced = np.where(energy > self.silence_threshold)[0]
        if len(voiced) == 0:
            return None  # pure silence — nothing to transcribe

        start = max(0, voiced[0] * win - self.silence_margin)
        end = min(len(audio), (voiced[-1] + 1) * win + self.silence_margin)
        trimmed = audio[start:end]
        raw_len = len(audio)
        pct = (1 - len(trimmed) / raw_len) * 100 if raw_len else 0
        return trimmed, pct

    # ── WAV encoding ─────────────────────────────────────────────────────────

    def encode_wav(self, audio: np.ndarray) -> io.BytesIO:
        """Encode numpy audio array to an in-memory WAV file."""
        wav_io = io.BytesIO()
        sf.write(wav_io, audio, self.sample_rate, format="WAV")
        wav_io.seek(0)
        return wav_io

    # ── Device enumeration ───────────────────────────────────────────────────

    @staticmethod
    def list_input_devices() -> List[Tuple[int, str]]:
        """Return [(index, name), ...] for all input-capable devices."""
        devices = sd.query_devices()
        result: List[Tuple[int, str]] = []
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:  # type: ignore[index]
                result.append((i, d["name"]))  # type: ignore[index]
        return result

    # ── Internal ─────────────────────────────────────────────────────────────

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        """PortAudio callback — enqueues frames while recording."""
        self._last_callback_time = time.monotonic()
        if status:
            log.debug("Audio callback status: %s", status)
        if self._recording.is_set():
            self._queue.put(indata.copy())


def play_beep(freqs: Tuple[float, float], duration_ms: int = 80, block: bool = False) -> None:
    """Play a two-tone beep through the system audio.

    *freqs* is a pair of frequencies in Hz (tone-1, tone-2).
    Each tone lasts *duration_ms* milliseconds.
    When *block* is False (default) the beep runs on a daemon thread
    so it never blocks the caller. On Windows this uses a synthesized
    in-memory WAV with ``winsound.PlaySound`` so start/stop cues remain
    distinct regardless of the user's system sound theme, without using
    the unstable tone-generator API.
    """
    def _build_tone_sequence() -> np.ndarray:
        sr = 44100
        vol = 0.28
        parts = []
        for freq in freqs:
            t = np.linspace(
                0,
                duration_ms / 1000,
                int(sr * duration_ms / 1000),
                endpoint=False,
                dtype=np.float32,
            )
            tone = (vol * np.sin(2 * np.pi * freq * t)).astype(np.float32)
            fade = int(sr * 0.006)
            if 0 < fade < len(tone):
                ramp = np.linspace(0, 1, fade, dtype=np.float32)
                tone[:fade] *= ramp
                tone[-fade:] *= ramp[::-1]
            parts.append(tone)
        return np.concatenate(parts)

    def _beep() -> None:
        try:
            samples = _build_tone_sequence()
            if sys.platform == "win32":
                import winsound
                wav_io = io.BytesIO()
                sf.write(wav_io, samples, 44100, format="WAV")
                winsound.PlaySound(wav_io.getvalue(), winsound.SND_MEMORY)
            else:
                sd.play(samples, samplerate=44100)
                sd.wait()
        except Exception:
            log.debug("Beep playback failed", exc_info=True)

    t = threading.Thread(target=_beep, daemon=True)
    t.start()
    if block:
        t.join()
