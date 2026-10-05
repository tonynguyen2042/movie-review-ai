"""T017 acceptance: Whisper adapter maps output without requiring MLX."""

import importlib.util
import math
from pathlib import Path

import pytest

from movie_review.asr.port import ASRError, ASRPort, ModelUnavailableError
from movie_review.asr.whisper_mlx import WhisperMLXAdapter, map_segments

_HAS_MLX = importlib.util.find_spec("mlx_whisper") is not None


def _raw() -> list[dict[str, object]]:
    return [
        {"start": 0.0, "end": 2.5, "text": "Hello world", "avg_logprob": -0.2},
        {"start": 2.5, "end": 4.0, "text": "", "confidence": 0.5},
    ]


def test_map_segments() -> None:
    segments = map_segments(_raw(), "en")
    assert [s.segment_id for s in segments] == ["seg_00000", "seg_00001"]
    assert segments[0].confidence == pytest.approx(math.exp(-0.2))
    assert segments[1].confidence == pytest.approx(0.5)
    assert segments[1].text == ""
    assert all(s.language == "en" for s in segments)


def test_map_segments_rejects_bad_raw() -> None:
    with pytest.raises(ASRError):
        map_segments([{"end": 1.0}], "en")
    with pytest.raises(ASRError):
        map_segments([{"start": 5.0, "end": 1.0, "text": "x"}], "en")


def test_adapter_uses_injected_transcriber(tmp_path: Path) -> None:
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"fake-audio")
    seen: dict[str, object] = {}

    def _fake(path: str, language: str | None) -> list[dict[str, object]]:
        seen["path"] = path
        seen["language"] = language
        return _raw()

    adapter = WhisperMLXAdapter("custom-model-name", transcriber=_fake)
    assert adapter.model == "custom-model-name"
    assert isinstance(adapter, ASRPort)
    segments = adapter.transcribe(audio)
    assert len(segments) == 2
    assert seen == {"path": str(audio), "language": "en"}
    vietnamese = adapter.transcribe(audio, language="vi")
    assert all(s.language == "vi" for s in vietnamese)


def test_adapter_missing_audio_rejected(tmp_path: Path) -> None:
    adapter = WhisperMLXAdapter("m", transcriber=lambda p, lang: [])
    with pytest.raises(ASRError, match="not found"):
        adapter.transcribe(tmp_path / "absent.wav")


def test_adapter_unload_releases_backend(tmp_path: Path) -> None:
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"x")
    adapter = WhisperMLXAdapter("m", transcriber=lambda p, lang: _raw())
    adapter.transcribe(audio)
    adapter.unload()
    if _HAS_MLX:
        pytest.skip("MLX runtime present; unload path differs")
    with pytest.raises(ModelUnavailableError):
        adapter.transcribe(audio)


def test_adapter_without_runtime_unavailable(tmp_path: Path) -> None:
    if _HAS_MLX:
        pytest.skip("MLX runtime present on this host")
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"x")
    adapter = WhisperMLXAdapter("whisper-large-v3-turbo")
    with pytest.raises(ModelUnavailableError, match="whisper-large-v3-turbo"):
        adapter.transcribe(audio)
