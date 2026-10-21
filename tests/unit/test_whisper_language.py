"""The configured language must reach the Whisper backend.

T126 regression. The local Whisper adapter accepted a `language` argument and
never used it, so the model auto-detected every time. The orchestrator's own
comment claimed the opposite -- that telling the model the language "skips a
detection pass" -- and the transcript rows and the cache key both recorded
the language that was asked for, whatever the audio actually was.
"""

from __future__ import annotations

from typing import Any

from movie_review.asr.whisper_mlx import _transcribe_with


class _RecordingWhisper:
    """A stand-in for the mlx_whisper module that records the call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def transcribe(self, audio_path: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((audio_path, kwargs))
        return {"segments": []}


def test_the_language_is_passed_to_whisper() -> None:
    whisper = _RecordingWhisper()
    _transcribe_with(whisper, "whisper-large-v3-turbo", "a.wav", "ja")
    assert whisper.calls == [
        ("a.wav", {"path_or_hf_repo": "whisper-large-v3-turbo", "language": "ja"})
    ]


def test_no_language_leaves_the_detection_to_whisper() -> None:
    """Omitting the language must still auto-detect, not pass None."""
    whisper = _RecordingWhisper()
    _transcribe_with(whisper, "whisper-large-v3-turbo", "a.wav", None)
    assert whisper.calls == [("a.wav", {"path_or_hf_repo": "whisper-large-v3-turbo"})]


def test_an_empty_language_is_treated_as_no_language() -> None:
    whisper = _RecordingWhisper()
    _transcribe_with(whisper, "m", "a.wav", "")
    assert "language" not in whisper.calls[0][1]
