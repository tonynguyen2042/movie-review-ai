"""Dialogue audio extraction for ASR (T018).

Produces a 16 kHz mono PCM WAV mixed down from the source. No source
separation is performed: ``dialogue.wav`` is the full mix, and separating
dialogue from music/effects is out of V1 scope.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from movie_review.media import ffmpeg as ff
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1


class AudioExtractionError(Exception):
    """Audio extraction failed in a classified way."""


def extract_dialogue_audio(
    source: str | Path,
    dest: str | Path,
    ffmpeg: str = "ffmpeg",
    run_fn: Callable[..., str] = ff.check,
) -> Path:
    """Extract ``dest`` as 16 kHz mono WAV; raises :class:`AudioExtractionError`."""
    src = Path(source)
    if not src.is_file():
        raise AudioExtractionError(f"Input file not found: {src}")
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_fn(
            ffmpeg,
            [
                "-y",
                "-v",
                "error",
                "-i",
                str(src),
                "-vn",
                "-ac",
                str(CHANNELS),
                "-ar",
                str(SAMPLE_RATE),
                "-c:a",
                "pcm_s16le",
                str(target),
            ],
        )
    except ff.ProcessError as exc:
        raise AudioExtractionError(f"Cannot extract audio from {src}: {exc}") from exc
    if not target.is_file():
        raise AudioExtractionError(f"Audio extraction produced no file for {src}")
    with ulog.logging_context(stage="transcript"):
        ulog.log_event(_logger, event="audio.extracted", status="ok")
    return target
