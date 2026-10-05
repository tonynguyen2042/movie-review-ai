"""TTS chunking: paragraphs → retryable audio files (T053, spec section 40).

Long paragraphs split at sentence boundaries (~60s max); short ones stay
whole for fine-grained retry, emotion changes, and paragraph editing. Each
chunk synthesizes independently through any :class:`TTSPort`.
"""

from __future__ import annotations

import logging
import re
import wave
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.domain import ReviewScript, SpeechAudio, TTSRequest
from movie_review.tts.port import TTSPort
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

WORDS_PER_60S = 150
_CHUNK_DIR = "tts"

_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True)
class TTSChunk:
    """One synthesizable unit with a stable ID."""

    chunk_id: str
    paragraph_id: str
    section_id: str
    text: str
    voice: str
    emotion: str
    speed: float


@dataclass(frozen=True)
class ChunkResult:
    """Synthesized chunk with its file and measured duration."""

    chunk: TTSChunk
    path: Path
    duration_seconds: float


def split_sentences(text: str) -> list[str]:
    """Naive sentence split on end punctuation (documented limitation)."""
    return [part.strip() for part in _SENTENCE_RE.split(text.strip()) if part.strip()]


def plan_chunks(
    script: ReviewScript,
    voice: str,
    emotion: str = "neutral",
    speed: float = 1.0,
    max_words: int = WORDS_PER_60S,
) -> list[TTSChunk]:
    """Plan one chunk per paragraph, splitting overlong ones by sentence."""
    chunks: list[TTSChunk] = []
    counter = 0
    for section in script.sections:
        for paragraph in section.paragraphs:
            texts = [paragraph.text]
            if len(paragraph.text.split()) > max_words:
                texts = split_sentences(paragraph.text)
            for text in texts:
                counter += 1
                chunks.append(
                    TTSChunk(
                        chunk_id=f"tts_{counter:03d}",
                        paragraph_id=paragraph.id,
                        section_id=section.id,
                        text=text,
                        voice=voice,
                        emotion=emotion,
                        speed=speed,
                    )
                )
    return chunks


def chunk_filename(chunk_id: str) -> str:
    """Deterministic chunk filename."""
    return f"{chunk_id}.wav"


def write_wav(path: str | Path, audio: SpeechAudio) -> Path:
    """Write 16-bit mono WAV; returns the path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(audio.sample_rate)
        wav.writeframes(audio.audio)
    return target


def synthesize_chunk(
    chunk: TTSChunk,
    port: TTSPort,
    jobs_dir: str | Path,
    job_id: str,
) -> ChunkResult:
    """Synthesize one chunk to its deterministic file."""
    audio = port.synthesize(
        TTSRequest(text=chunk.text, voice=chunk.voice, emotion=chunk.emotion, speed=chunk.speed)
    )
    path = write_wav(
        artifacts.artifact_path(jobs_dir, job_id, _CHUNK_DIR, chunk_filename(chunk.chunk_id)),
        audio,
    )
    with ulog.logging_context(job_id=job_id, stage="tts"):
        ulog.log_event(_logger, event="chunk.synthesized", status="ok", chunk=chunk.chunk_id)
    return ChunkResult(chunk=chunk, path=path, duration_seconds=audio.duration_seconds)


def synthesize_chunks(
    chunks: list[TTSChunk],
    port: TTSPort,
    jobs_dir: str | Path,
    job_id: str,
) -> list[ChunkResult]:
    """Synthesize chunks in order (retry granularity stays per chunk)."""
    try:
        return [synthesize_chunk(chunk, port, jobs_dir, job_id) for chunk in chunks]
    finally:
        port.unload()
