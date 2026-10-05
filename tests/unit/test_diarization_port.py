"""T020 acceptance: diarization contract and port behavior."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from movie_review.diarization.port import (
    DiarizationError,
    DiarizationModelUnavailableError,
    DiarizationPort,
)
from movie_review.domain import DiarizedSegment


def test_segment_valid() -> None:
    segment = DiarizedSegment(speaker="SPEAKER_00", start=1.0, end=2.5)
    assert DiarizedSegment.model_validate(segment.model_dump()) == segment


@pytest.mark.parametrize("label", ["John", "SPK1", "SPEAKER", "", "speaker_00"])
def test_segment_rejects_non_labels(label: str) -> None:
    with pytest.raises(ValidationError):
        DiarizedSegment(speaker=label, start=0.0, end=1.0)


def test_segment_rejects_inverted_span() -> None:
    with pytest.raises(ValidationError):
        DiarizedSegment(speaker="SPEAKER_01", start=2.0, end=1.0)


class _FakeDiarizer(DiarizationPort):
    def __init__(self, segments: list[DiarizedSegment]) -> None:
        self._segments = segments
        self.unloaded = False

    def diarize(self, audio_path: str | Path) -> list[DiarizedSegment]:
        assert Path(audio_path).suffix == ".wav"
        return list(self._segments)

    def unload(self) -> None:
        self.unloaded = True


def test_port_contract() -> None:
    fake = _FakeDiarizer([DiarizedSegment(speaker="SPEAKER_01", start=0.0, end=1.0)])
    [segment] = fake.diarize("audio.wav")
    assert segment.speaker == "SPEAKER_01"
    fake.unload()
    assert fake.unloaded is True


def test_port_requires_methods() -> None:
    with pytest.raises(TypeError):
        DiarizationPort()  # type: ignore[abstract]


def test_model_unavailable_error() -> None:
    error = DiarizationModelUnavailableError("pyannote", "no token configured")
    assert isinstance(error, DiarizationError)
    assert "pyannote" in str(error)
