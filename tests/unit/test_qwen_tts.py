"""T052 acceptance: Qwen3-TTS adapter measures output without requiring MLX."""

import importlib.util

import pytest

from movie_review.domain import TTSRequest
from movie_review.tts.port import TTSError, TTSPort, TTSUnavailableError
from movie_review.tts.qwen_tts import QwenTTSAdapter

_HAS_MLX = importlib.util.find_spec("mlx_audio") is not None


def _request__qwen_tts() -> TTSRequest:
    return TTSRequest(text="Hello world.", voice="Ryan")


def test_duration_measured_from_bytes() -> None:
    adapter = QwenTTSAdapter("m", backend=lambda request: (b"\x00" * 32000, 16000))
    audio = adapter.synthesize(_request__qwen_tts())
    assert audio.duration_seconds == pytest.approx(1.0)
    assert audio.sample_rate == 16000
    assert isinstance(adapter, TTSPort)


def test_empty_audio_allowed() -> None:
    adapter = QwenTTSAdapter("m", backend=lambda request: (b"", 16000))
    assert adapter.synthesize(_request__qwen_tts()).duration_seconds == 0.0


def test_bad_sample_rate_rejected() -> None:
    adapter = QwenTTSAdapter("m", backend=lambda request: (b"\x00" * 10, 0))
    with pytest.raises(TTSError, match="sample rate"):
        adapter.synthesize(_request__qwen_tts())


def test_backend_failure_wrapped() -> None:
    def _fail(request: TTSRequest) -> tuple[bytes, int]:
        raise RuntimeError("backend exploded")

    adapter = QwenTTSAdapter("m", backend=_fail)
    with pytest.raises(TTSError, match="synthesis failed"):
        adapter.synthesize(_request__qwen_tts())


def test_model_identity() -> None:
    assert QwenTTSAdapter("custom-tts").model == "custom-tts"


def test_unload_releases_backend() -> None:
    adapter = QwenTTSAdapter("m", backend=lambda request: (b"\x00", 16000))
    adapter.synthesize(_request__qwen_tts())
    adapter.unload()
    if _HAS_MLX:
        pytest.skip("MLX runtime present; unload path differs")
    with pytest.raises(TTSUnavailableError):
        adapter.synthesize(_request__qwen_tts())


def test_without_runtime_unavailable() -> None:
    if _HAS_MLX:
        pytest.skip("MLX runtime present on this host")
    adapter = QwenTTSAdapter("Qwen3-TTS-1.7B")
    with pytest.raises(TTSUnavailableError, match="Qwen3-TTS-1.7B"):
        adapter.synthesize(_request__qwen_tts())
