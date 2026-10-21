"""T016 acceptance: transcript contract and ASR port behavior."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from movie_review.asr.port import ASRError, ASRPort, ModelUnavailableError
from movie_review.domain import TranscriptSegment
from tests.helpers import (
    _segment,
)


def test_segment_valid() -> None:
    segment = _segment()
    assert segment.text.startswith("Where")
    assert TranscriptSegment.model_validate(segment.model_dump()) == segment


def test_segment_rejects_inverted_span() -> None:
    with pytest.raises(ValidationError):
        TranscriptSegment(segment_id="s", start=5.0, end=4.0, text="x")


def test_segment_rejects_bad_confidence() -> None:
    with pytest.raises(ValidationError):
        TranscriptSegment(segment_id="s", start=0.0, end=1.0, confidence=2.0)


def test_segment_allows_empty_text() -> None:
    assert TranscriptSegment(segment_id="s", start=0.0, end=1.0).text == ""


class _FakeASR(ASRPort):
    def __init__(self, segments: list[TranscriptSegment]) -> None:
        self._segments = segments
        self.unloaded = False

    def transcribe(
        self, audio_path: str | Path, *, language: str | None = None
    ) -> list[TranscriptSegment]:
        assert Path(audio_path).suffix == ".wav"
        return [s.model_copy(update={"language": language or s.language}) for s in self._segments]

    def unload(self) -> None:
        self.unloaded = True


def test_port_contract() -> None:
    fake = _FakeASR([_segment()])
    [segment] = fake.transcribe("audio.wav", language="vi")
    assert segment.language == "vi"
    fake.unload()
    assert fake.unloaded is True


def test_port_requires_transcribe() -> None:
    with pytest.raises(TypeError):
        ASRPort()  # type: ignore[abstract]


def test_model_unavailable_error() -> None:
    error = ModelUnavailableError("whisper-large-v3-turbo", "no MLX on this host")
    assert isinstance(error, ASRError)
    assert "whisper-large-v3-turbo" in str(error)
