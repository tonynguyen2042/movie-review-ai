"""Remote ASR adapter for OpenAI-compatible transcription endpoints.

Targets ``POST /audio/transcriptions`` as served by faster-whisper-server or
any OpenAI-compatible speech-to-text host. whisper.cpp's ``whisper-server`` does
not implement that route -- it serves ``POST /inference`` with the same
``verbose_json`` response shape -- so ``endpoint_path`` overrides it. Audio is
uploaded as multipart form data, so the orchestrating host never needs the MLX
runtime or the model weights.

The response is mapped through :func:`movie_review.asr.whisper_mlx.map_segments`
so segment validation and confidence handling are identical to the local path.
whisper.cpp supplies ``avg_logprob`` per segment, which ``map_segments`` already
reads for confidence.
"""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path
from typing import Any

from movie_review.asr.port import ASRError, ASRPort, ModelUnavailableError
from movie_review.asr.whisper_mlx import DEFAULT_LANGUAGE, map_segments
from movie_review.domain.transcript import TranscriptSegment
from movie_review.remote import http

TRANSCRIPTIONS_PATH = "/audio/transcriptions"

#: How much audio one request carries. Ten minutes of 16 kHz mono PCM is
#: about 19 MB, which a remote endpoint can be asked for in one request.
DEFAULT_SEGMENT_SECONDS = 600.0


def split_wav(
    path: str | Path,
    dest_dir: str | Path,
    segment_seconds: float = DEFAULT_SEGMENT_SECONDS,
) -> list[tuple[Path, float]]:
    """Split a WAV into segments; returns each file and its offset in seconds.

    A 2 h film is 230 MB of 16 kHz mono PCM, and the whole thing used to be
    posted in one request under a 120 s timeout. Over anything slower than a
    LAN that times out, and the whole ASR stage fails with no way to retry a
    fraction of the work.
    """
    source = Path(path)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[tuple[Path, float]] = []

    with wave.open(str(source), "rb") as wav:
        params = wav.getparams()
        rate = params.framerate
        if rate <= 0:
            raise ASRError(f"Invalid WAV rate in {source}")
        frames_per_segment = max(1, int(rate * segment_seconds))
        total = wav.getnframes()
        index = 0
        while wav.tell() < total:
            frames = wav.readframes(frames_per_segment)
            if not frames:
                break
            target = dest / f"{source.stem}_part_{index:03d}.wav"
            with wave.open(str(target), "wb") as out:
                out.setnchannels(params.nchannels)
                out.setsampwidth(params.sampwidth)
                out.setframerate(params.framerate)
                out.writeframes(frames)
            written.append((target, index * frames_per_segment / rate))
            index += 1

    return written


class OpenAICompatASRAdapter(ASRPort):
    """Speech-to-text against a remote OpenAI-compatible endpoint."""

    def __init__(
        self,
        model: str,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = http.DEFAULT_TIMEOUT_SECONDS,
        retry: http.TransportRetry = http.DEFAULT_RETRY,
        transport: http.RawTransport | None = None,
        endpoint_path: str | None = None,
        segment_seconds: float = DEFAULT_SEGMENT_SECONDS,
    ) -> None:
        if not base_url:
            raise ASRError("base_url is required for a remote ASR adapter")
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._retry = retry
        self._transport = transport
        self._endpoint_path = endpoint_path
        self._segment_seconds = segment_seconds

    @property
    def model(self) -> str:
        """Configured model identity."""
        return self._model

    @property
    def base_url(self) -> str:
        """Configured remote endpoint."""
        return self._base_url

    @property
    def endpoint_path(self) -> str:
        """Route this adapter posts to, defaulting to the OpenAI one."""
        return self._endpoint_path or TRANSCRIPTIONS_PATH

    def transcribe(
        self, audio_path: str | Path, *, language: str | None = None
    ) -> list[TranscriptSegment]:
        """Upload the audio and return timestamped segments.

        The audio is uploaded in bounded segments rather than in one
        request, and the timestamps each returns are offset back to movie
        time.
        """
        source = Path(audio_path)
        if not source.is_file():
            raise ASRError(f"Audio file does not exist: {source}")

        url = http.build_endpoint(self._base_url, self.endpoint_path)
        fields = {
            "model": self._model,
            # verbose_json is what carries per-segment timestamps; plain
            # json_format returns only a single blob of text. whisper.cpp
            # supports the same value and returns the same segment shape.
            "response_format": "verbose_json",
        }
        if language:
            fields["language"] = language

        raw: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix="movie-review-asr-") as tmp:
            parts = split_wav(source, tmp, self._segment_seconds)
            for path, offset in parts:
                try:
                    body = http.post_multipart(
                        url,
                        fields,
                        {"file": http.file_upload(path)},
                        api_key=self._api_key,
                        timeout=self._timeout,
                        transport=self._transport,
                        retry=self._retry,
                    )
                    document = http.decode_json(body, url)
                except http.RemoteUnavailableError as exc:
                    raise ModelUnavailableError(self._model, str(exc)) from exc
                except http.RemoteProtocolError as exc:
                    raise ASRError(str(exc)) from exc

                for segment in self._raw_segments(document, url):
                    # The endpoint timestamps its own segment, so the offset
                    # of the segment within the movie has to be added back.
                    segment["start"] = float(segment.get("start", 0.0)) + offset
                    segment["end"] = float(segment.get("end", 0.0)) + offset
                    raw.append(segment)

        return map_segments(raw, language or DEFAULT_LANGUAGE)

    def _raw_segments(self, document: Any, url: str) -> list[dict[str, Any]]:
        """The raw segment list of a response, validated."""
        if not isinstance(document, dict):
            raise ASRError(f"ASR response from {url} is not a JSON object")

        raw_segments = document.get("segments")
        if not isinstance(raw_segments, list) or not raw_segments:
            detail = "returned text without timestamps"
            if isinstance(document.get("text"), str) and document["text"].strip():
                detail += "; request response_format=verbose_json"
            raise ASRError(f"ASR response from {url} {detail}")
        return [segment for segment in raw_segments if isinstance(segment, dict)]

    def _segments_from(
        self, document: Any, url: str, language: str | None
    ) -> list[TranscriptSegment]:
        """Extract and validate segments, rejecting text-only replies."""
        return map_segments(self._raw_segments(document, url), language or DEFAULT_LANGUAGE)

    def unload(self) -> None:
        """No local weights are held; the remote host owns the model."""
        return None

    def available(self) -> bool:
        """True when the endpoint is configured well enough to attempt a call."""
        return bool(self._base_url and self._model)
