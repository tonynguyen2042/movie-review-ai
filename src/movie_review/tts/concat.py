"""TTS concatenation: chunk WAVs → master narration (T054, spec section 42).

Joins validated 16-bit mono chunk files in order with a JSON metadata
sidecar (spec section 41). Parameter mismatches fail loudly instead of
silently resampling; normalization and mixing belong to later stages.
"""

from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from movie_review.artifacts import manager as artifacts
from movie_review.tts.chunks import ChunkResult
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

NARRATION_FILENAME = "narration.wav"
METADATA_FILENAME = "narration.json"


class ConcatError(Exception):
    """Concatenation failed in a classified way."""


@dataclass(frozen=True)
class ConcatResult:
    """Concatenated narration with per-chunk metadata."""

    path: Path
    metadata_path: Path
    duration_seconds: float
    segments: list[dict[str, Any]]


def _read_wav(path: Path) -> tuple[wave._wave_params, bytes]:
    try:
        with wave.open(str(path), "rb") as wav:
            return wav.getparams(), wav.readframes(wav.getnframes())
    except (wave.Error, OSError) as exc:
        raise ConcatError(f"Cannot read chunk {path}: {exc}") from exc


def concatenate(
    chunks: list[ChunkResult],
    dest: str | Path,
    metadata_dest: str | Path | None = None,
) -> ConcatResult:
    """Join chunk files in order; writes narration WAV plus metadata JSON."""
    if not chunks:
        raise ConcatError("Nothing to concatenate")
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)

    frames: list[bytes] = []
    params = None
    segments: list[dict[str, Any]] = []
    for result in chunks:
        chunk_params, data = _read_wav(result.path)
        if params is None:
            params = chunk_params
        elif (chunk_params.nchannels, chunk_params.sampwidth, chunk_params.framerate) != (
            params.nchannels,
            params.sampwidth,
            params.framerate,
        ):
            raise ConcatError(f"Parameter mismatch in chunk {result.path}")
        frames.append(data)
        segments.append(
            {
                "paragraph_id": result.chunk.paragraph_id,
                "chunk_id": result.chunk.chunk_id,
                "audio_file": result.path.name,
                "duration": result.duration_seconds,
                "voice": result.chunk.voice,
                "emotion": result.chunk.emotion,
                "speed": result.chunk.speed,
            }
        )

    assert params is not None
    frame_bytes = params.nchannels * params.sampwidth
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(params.nchannels)
        wav.setsampwidth(params.sampwidth)
        wav.setframerate(params.framerate)
        wav.writeframes(b"".join(frames))
    duration = sum(len(part) / frame_bytes / params.framerate for part in frames)
    meta_path = Path(metadata_dest) if metadata_dest else target.with_suffix(".json")
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts.write_json(meta_path, {"segments": segments, "duration_seconds": duration})
    with ulog.logging_context(stage="tts"):
        ulog.log_event(_logger, event="concat.completed", status="ok", chunks=len(chunks))
    return ConcatResult(
        path=target,
        metadata_path=meta_path,
        duration_seconds=duration,
        segments=segments,
    )
