"""The audio must be uploaded in bounded pieces, not all at once.

T135 regression. The whole audio file was posted in one multipart request.
The dialogue audio is 16 kHz mono PCM, so a 2 h film is 230 MB in a single
POST under a 120 s default timeout. Over anything slower than a LAN that
times out, and the whole ASR stage fails with no way to retry a fraction of
the work.

The audio is now cut into segments, each segment is uploaded on its own, and
the timestamps the endpoint returns are offset back to movie time.
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

from movie_review.asr.openai_compat import OpenAICompatASRAdapter, split_wav


def _audio(path: Path, seconds: float, rate: int = 8000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def _body(segments: list[dict[str, Any]]) -> bytes:
    import json

    return json.dumps({"segments": segments}).encode("utf-8")


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_split_wav_cuts_the_audio_and_offsets_the_parts(tmp_path: Path) -> None:
    source = _audio(tmp_path / "audio.wav", 30.0, rate=8000)
    parts = split_wav(source, tmp_path / "parts", segment_seconds=10.0)

    assert len(parts) == 3
    assert [offset for _, offset in parts] == [0.0, 10.0, 20.0]
    for path, _ in parts:
        assert path.is_file()
        with wave.open(str(path), "rb") as wav:
            assert wav.getnframes() == 8000 * 10


def test_short_audio_is_one_segment(tmp_path: Path) -> None:
    source = _audio(tmp_path / "audio.wav", 3.0, rate=8000)
    parts = split_wav(source, tmp_path / "parts", segment_seconds=600.0)
    assert len(parts) == 1
    assert parts[0][1] == 0.0


def test_the_transcript_offsets_the_timestamps_back_to_movie_time(tmp_path: Path) -> None:
    """Each part is timestamped on its own, so the offset has to be added."""
    source = _audio(tmp_path / "audio.wav", 30.0, rate=8000)
    uploads: list[bytes] = []

    def transport(request: Any, timeout: float) -> _FakeResponse:
        uploads.append(request.data)
        # Every part answers with the same relative timestamps.
        return _FakeResponse(
            _body(
                [
                    {"start": 0.0, "end": 1.0, "text": "line one"},
                    {"start": 1.0, "end": 2.0, "text": "line two"},
                ]
            )
        )

    adapter = OpenAICompatASRAdapter(
        "whisper-large-v3-turbo",
        "http://gpu:9000/v1",
        transport=transport,
        segment_seconds=10.0,
    )
    segments = adapter.transcribe(source, language="en")

    assert len(uploads) == 3, "the audio was not uploaded in pieces"
    assert len(segments) == 6

    # The three parts are offset by 0, 10 and 20 seconds.
    assert segments[0].start == 0.0
    assert segments[2].start == 10.0
    assert segments[4].start == 20.0
    assert segments[4].end == 21.0
    assert segments[5].start == 21.0
    assert segments[5].end == 22.0


def test_the_uploaded_body_is_bounded(tmp_path: Path) -> None:
    """No request may carry more than one segment's worth of audio."""
    source = _audio(tmp_path / "audio.wav", 60.0, rate=8000)
    sizes: list[int] = []

    def transport(request: Any, timeout: float) -> _FakeResponse:
        sizes.append(len(request.data))
        return _FakeResponse(_body([{"start": 0.0, "end": 1.0, "text": "x"}]))

    adapter = OpenAICompatASRAdapter(
        "whisper-large-v3-turbo",
        "http://gpu:9000/v1",
        transport=transport,
        segment_seconds=10.0,
    )
    adapter.transcribe(source, language="en")

    assert len(sizes) == 6
    assert max(sizes) < 200_000, f"a request carried {max(sizes)} bytes"
