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

from pathlib import Path
from typing import Any

from movie_review.asr.port import ASRError, ASRPort, ModelUnavailableError
from movie_review.asr.whisper_mlx import DEFAULT_LANGUAGE, map_segments
from movie_review.domain.transcript import TranscriptSegment
from movie_review.remote import http

TRANSCRIPTIONS_PATH = "/audio/transcriptions"


class OpenAICompatASRAdapter(ASRPort):
    """Speech-to-text against a remote OpenAI-compatible endpoint."""

    def __init__(
        self,
        model: str,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = http.DEFAULT_TIMEOUT_SECONDS,
        transport: http.RawTransport | None = None,
        endpoint_path: str | None = None,
    ) -> None:
        if not base_url:
            raise ASRError("base_url is required for a remote ASR adapter")
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._transport = transport
        self._endpoint_path = endpoint_path

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
        """Upload one audio file and return timestamped segments."""
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

        try:
            body = http.post_multipart(
                url,
                fields,
                {"file": http.file_upload(source)},
                api_key=self._api_key,
                timeout=self._timeout,
                transport=self._transport,
            )
            document = http.decode_json(body, url)
        except http.RemoteUnavailableError as exc:
            raise ModelUnavailableError(self._model, str(exc)) from exc
        except http.RemoteProtocolError as exc:
            raise ASRError(str(exc)) from exc

        return self._segments_from(document, url, language)

    def _segments_from(
        self, document: Any, url: str, language: str | None
    ) -> list[TranscriptSegment]:
        """Extract and validate segments, rejecting text-only replies."""
        if not isinstance(document, dict):
            raise ASRError(f"ASR response from {url} is not a JSON object")

        raw_segments = document.get("segments")
        if not isinstance(raw_segments, list) or not raw_segments:
            detail = "returned text without timestamps"
            if isinstance(document.get("text"), str) and document["text"].strip():
                detail += "; request response_format=verbose_json"
            raise ASRError(f"ASR response from {url} {detail}")
        return map_segments(raw_segments, language or DEFAULT_LANGUAGE)

    def unload(self) -> None:
        """No local weights are held; the remote host owns the model."""
        return None

    def available(self) -> bool:
        """True when the endpoint is configured well enough to attempt a call."""
        return bool(self._base_url and self._model)
