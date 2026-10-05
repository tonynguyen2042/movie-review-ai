"""Initial diarization adapter: energy voice activity (T021).

Baseline speaker segmentation without ML models: speech-active spans are
detected by RMS energy and every span is labeled ``SPEAKER_00``. This does
NOT distinguish speakers — alternating labels would fabricate turns.
Embedding-based adapters will replace this baseline later.
"""

from __future__ import annotations

import logging
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from movie_review.diarization.port import DiarizationError, DiarizationPort
from movie_review.domain.diarization import DiarizedSegment
from movie_review.media import ffmpeg as ff
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_MS = 20
HOP_MS = 10
SILENCE_THRESHOLD = 400.0
MIN_SPEECH_MS = 250
MIN_SILENCE_MS = 400
PAD_MS = 100


@dataclass(frozen=True)
class VadConfig:
    """Tunable energy detector parameters (documented defaults, no hard-coding)."""

    sample_rate: int = SAMPLE_RATE
    frame_ms: int = FRAME_MS
    hop_ms: int = HOP_MS
    silence_threshold: float = SILENCE_THRESHOLD
    min_speech_ms: int = MIN_SPEECH_MS
    min_silence_ms: int = MIN_SILENCE_MS
    pad_ms: int = PAD_MS


def read_mono_pcm16(path: str | Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Read WAV PCM directly; decode other containers via ffmpeg first."""
    src = Path(path)
    if not src.is_file():
        raise DiarizationError(f"Audio file not found: {src}")
    if src.suffix.lower() == ".wav":
        try:
            with wave.open(str(src), "rb") as wav:
                if wav.getsampwidth() != 2:
                    raise DiarizationError(f"Only 16-bit WAV supported: {src}")
                frames = wav.readframes(wav.getnframes())
                channels = wav.getnchannels()
                rate = wav.getframerate()
        except (wave.Error, OSError) as exc:
            raise DiarizationError(f"Cannot read WAV {src}: {exc}") from exc
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        if rate != sample_rate:
            raise DiarizationError(f"Expected {sample_rate} Hz WAV, got {rate} Hz: {src}")
        return samples
    with tempfile.TemporaryDirectory(prefix="diarize-") as tmp:
        decoded = Path(tmp) / "decode.wav"
        try:
            ff.check(
                "ffmpeg",
                [
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(src),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    str(sample_rate),
                    "-c:a",
                    "pcm_s16le",
                    str(decoded),
                ],
            )
        except ff.FFmpegError as exc:
            raise DiarizationError(f"Cannot decode {src}: {exc}") from exc
        return read_mono_pcm16(decoded, sample_rate)


def detect_speech_spans(samples: np.ndarray, config: VadConfig) -> list[tuple[float, float]]:
    """Energy VAD: return ``(start, end)`` speech spans in seconds."""
    if samples.size == 0:
        return []
    frame_len = max(1, int(config.sample_rate * config.frame_ms / 1000))
    hop_len = max(1, int(config.sample_rate * config.hop_ms / 1000))
    if samples.size < frame_len:
        return []
    frames = np.lib.stride_tricks.sliding_window_view(samples, frame_len)[::hop_len]
    energy = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))
    speech = energy > config.silence_threshold

    min_silence = max(1, int(config.min_silence_ms / config.hop_ms))
    min_speech = max(1, int(config.min_speech_ms / config.hop_ms))
    pad = config.pad_ms / 1000.0
    duration = samples.shape[0] / config.sample_rate

    spans: list[tuple[float, float]] = []
    start: int | None = None
    silence_run = 0
    for index, active in enumerate(speech):
        if active:
            if start is None:
                start = index
            silence_run = 0
        elif start is not None:
            silence_run += 1
            if silence_run >= min_silence:
                end = index - silence_run
                if end - start >= min_speech:
                    spans.append((start, end))
                start = None
                silence_run = 0
    if start is not None and len(speech) - start >= min_speech:
        spans.append((start, len(speech)))
    hop_seconds = config.hop_ms / 1000.0
    return [
        (
            max(0.0, start_index * hop_seconds - pad),
            min(duration, (end_index + 1) * hop_seconds + pad),
        )
        for start_index, end_index in spans
    ]


class EnergyDiarizer(DiarizationPort):
    """Initial adapter: speech spans, all labeled ``SPEAKER_00``."""

    def __init__(self, config: VadConfig | None = None) -> None:
        self._config = config or VadConfig()

    @property
    def config(self) -> VadConfig:
        """Active detector parameters."""
        return self._config

    def diarize(self, audio_path: str | Path) -> list[DiarizedSegment]:
        samples = read_mono_pcm16(audio_path, self._config.sample_rate)
        spans = detect_speech_spans(samples, self._config)
        with ulog.logging_context(stage="diarization"):
            ulog.log_event(_logger, event="diarization.completed", status="ok", spans=len(spans))
        return [DiarizedSegment(speaker="SPEAKER_00", start=start, end=end) for start, end in spans]

    def unload(self) -> None:
        """No retained model state; contract no-op."""
