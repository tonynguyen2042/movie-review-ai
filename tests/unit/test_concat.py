"""T054 acceptance: ordered concatenation with metadata and loud mismatches."""

import wave
from pathlib import Path

import pytest

from movie_review.domain import SpeechAudio
from movie_review.tts.chunks import ChunkResult, TTSChunk, write_wav
from movie_review.tts.concat import ConcatError, concatenate


def _chunk(tmp_path: Path, chunk_id: str, paragraph_id: str, payload: bytes) -> ChunkResult:
    path = tmp_path / f"{chunk_id}.wav"
    write_wav(
        path,
        SpeechAudio(duration_seconds=len(payload) / 2 / 16000, sample_rate=16000, audio=payload),
    )
    return ChunkResult(
        chunk=TTSChunk(
            chunk_id=chunk_id,
            paragraph_id=paragraph_id,
            section_id="sec_01",
            text="words",
            voice="Ryan",
            emotion="neutral",
            speed=1.0,
        ),
        path=path,
        duration_seconds=len(payload) / 2 / 16000,
    )


def test_concat_order_and_duration(tmp_path: Path) -> None:
    first = _chunk(tmp_path, "tts_001", "p1", b"\x01" * 3200)
    second = _chunk(tmp_path, "tts_002", "p2", b"\x02" * 1600)
    result = concatenate([first, second], tmp_path / "narration.wav")
    assert result.duration_seconds == pytest.approx(0.1 + 0.05)
    with wave.open(str(result.path), "rb") as wav:
        data = wav.readframes(wav.getnframes())
    assert data == b"\x01" * 3200 + b"\x02" * 1600
    assert result.metadata_path == tmp_path / "narration.json"
    assert [s["paragraph_id"] for s in result.segments] == ["p1", "p2"]
    assert result.segments[0]["voice"] == "Ryan"
    assert result.segments[0]["duration"] == pytest.approx(0.1)


def test_concat_empty_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConcatError, match="Nothing to concatenate"):
        concatenate([], tmp_path / "out.wav")


def test_concat_param_mismatch_rejected(tmp_path: Path) -> None:
    first = _chunk(tmp_path, "tts_001", "p1", b"\x01" * 100)
    other = tmp_path / "other.wav"
    write_wav(other, SpeechAudio(duration_seconds=0.1, sample_rate=8000, audio=b"\x03" * 1600))
    second = ChunkResult(
        chunk=first.chunk,
        path=other,
        duration_seconds=0.1,
    )
    with pytest.raises(ConcatError, match="mismatch"):
        concatenate([first, second], tmp_path / "out.wav")


def test_concat_missing_file_rejected(tmp_path: Path) -> None:
    first = _chunk(tmp_path, "tts_001", "p1", b"\x01" * 100)
    ghost = ChunkResult(chunk=first.chunk, path=tmp_path / "ghost.wav", duration_seconds=0.1)
    with pytest.raises(ConcatError, match="Cannot read chunk"):
        concatenate([first, ghost], tmp_path / "out.wav")
