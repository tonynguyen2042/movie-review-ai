"""Audio mixing: narration plus optional ducked music bed (T060, spec 42-43).

Music ducks beneath active narration (energy speech spans from the T021
detector); without music the narration passes through peak-normalized.
Parameter mismatches fail loudly instead of silently resampling.
"""

from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from movie_review.diarization.initial import VadConfig, detect_speech_spans
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

TARGET_PEAK = 0.89
DUCKED_GAIN = 0.25
ATTACK_MS = 50
RELEASE_MS = 300


class MixError(Exception):
    """Audio mixing failed in a classified way."""


@dataclass(frozen=True)
class MixResult:
    """Mixed output with measured peak."""

    path: Path
    duration_seconds: float
    peak: float


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Read 16-bit mono WAV as float64 samples in [-1, 1] plus sample rate."""
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, OSError) as exc:
        raise MixError(f"Cannot read {path}: {exc}") from exc
    if channels != 1 or width != 2:
        raise MixError(f"Expected 16-bit mono WAV: {path}")
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64) / 32768.0
    return samples, rate


def write_wav(path: str | Path, samples: np.ndarray, rate: int) -> Path:
    """Write float samples as 16-bit mono WAV with clipping guard."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())
    return target


def normalize_peak(samples: np.ndarray, target: float = TARGET_PEAK) -> np.ndarray:
    """Scale to a target peak; silence stays silent."""
    peak = float(np.abs(samples).max(initial=0.0))
    if peak <= 0.0:
        return samples.copy()
    return samples * (target / peak)


def ducking_envelope(
    total: int, spans: list[tuple[float, float]], rate: int, ducked: float = DUCKED_GAIN
) -> np.ndarray:
    """Music gain envelope: ducked under speech with attack/release ramps."""
    envelope = np.ones(total)
    attack = max(1, int(rate * ATTACK_MS / 1000))
    release = max(1, int(rate * RELEASE_MS / 1000))
    for start, end in spans:
        first = max(0, int(start * rate))
        last = min(total, int(end * rate))
        if last <= first:
            continue
        envelope[first:last] = ducked
        ramp_up = slice(max(0, first - attack), first)
        envelope[ramp_up] = np.linspace(1.0, ducked, ramp_up.stop - ramp_up.start)
        ramp_down = slice(last, min(total, last + release))
        envelope[ramp_down] = np.linspace(ducked, 1.0, ramp_down.stop - ramp_down.start)
    return envelope


def mix(
    narration_path: str | Path,
    dest: str | Path,
    music_path: str | Path | None = None,
    music_gain: float = 1.0,
) -> MixResult:
    """Mix narration with an optional ducked music bed to ``dest``."""
    narration, rate = read_wav(narration_path)
    bed = np.zeros_like(narration)
    if music_path is not None:
        music, music_rate = read_wav(music_path)
        if music_rate != rate:
            raise MixError(f"Music rate {music_rate} != narration rate {rate}")
        if music.shape[0] >= narration.shape[0]:
            bed = music[: narration.shape[0]]
        else:
            bed[: music.shape[0]] = music
        spans = detect_speech_spans(narration, VadConfig(sample_rate=rate))
        bed = bed * ducking_envelope(narration.shape[0], spans, rate) * music_gain
    mixed = normalize_peak(narration + bed)
    out = write_wav(dest, mixed, rate)
    with ulog.logging_context(stage="audio-mix"):
        ulog.log_event(_logger, event="mix.completed", status="ok")
    return MixResult(
        path=out,
        duration_seconds=narration.shape[0] / rate,
        peak=float(np.abs(mixed).max(initial=0.0)),
    )
