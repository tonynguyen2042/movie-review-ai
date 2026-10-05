"""T051 acceptance: TTS contract and port behavior."""

import pytest
from pydantic import ValidationError

from movie_review.domain import SpeechAudio, TTSRequest
from movie_review.tts.port import TTSError, TTSPort, TTSUnavailableError


def test_request_validation() -> None:
    request = TTSRequest(text="Hello world.", voice="Ryan")
    assert request.emotion == "neutral"
    assert request.speed == 1.0
    with pytest.raises(ValidationError):
        TTSRequest(text="", voice="Ryan")
    with pytest.raises(ValidationError):
        TTSRequest(text="Hi.", voice="")
    with pytest.raises(ValidationError):
        TTSRequest(text="Hi.", voice="Ryan", speed=0.0)


def test_audio_validation() -> None:
    audio = SpeechAudio(duration_seconds=8.72, sample_rate=16000, audio=b"wav-bytes")
    assert SpeechAudio.model_validate(audio.model_dump()) == audio


class _FakeTTS(TTSPort):
    def __init__(self) -> None:
        self.unloaded = False
        self.seen: list[TTSRequest] = []

    def synthesize(self, request: TTSRequest) -> SpeechAudio:
        self.seen.append(request)
        return SpeechAudio(duration_seconds=1.0, sample_rate=16000, audio=b"fake")

    def unload(self) -> None:
        self.unloaded = True


def test_port_contract() -> None:
    fake = _FakeTTS()
    audio = fake.synthesize(TTSRequest(text="Hi.", voice="Ryan", emotion="dramatic"))
    assert audio.sample_rate == 16000
    assert fake.seen[0].emotion == "dramatic"
    fake.unload()
    assert fake.unloaded is True


def test_port_requires_methods() -> None:
    with pytest.raises(TypeError):
        TTSPort()  # type: ignore[abstract]


def test_unavailable_error() -> None:
    error = TTSUnavailableError("Qwen3-TTS-1.7B", "no MLX on this host")
    assert isinstance(error, TTSError)
    assert "Qwen3-TTS-1.7B" in str(error)
