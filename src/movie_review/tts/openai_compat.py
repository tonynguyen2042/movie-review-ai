"""Remote TTS adapter for OpenAI-compatible speech endpoints.

Targets ``POST /audio/speech`` as served by OpenAI-compatible servers and
self-hosted TTS front-ends. Text goes up, audio bytes come back.

Duration is **measured from the returned bytes**, never taken from server
metadata (the same rule the local adapter follows), because a wrong duration
propagates into subtitle timing and the render manifest. That requires a
self-describing container:

* ``wav``  -- parsed with :mod:`wave` (sample rate, channels, width read from
  the header). This is the recommended format.
* ``pcm``  -- headerless; the caller must supply the sample rate, channels,
  and sample width, so duration is still derived from bytes rather than trusted.

``mp3`` and other compressed formats are rejected with an explicit message
instead of guessing: decoding compressed audio is out of scope here, and
guessing a duration would corrupt downstream timing.
"""

from __future__ import annotations

import io
import wave

from movie_review.domain.tts import SpeechAudio, TTSRequest
from movie_review.remote import http
from movie_review.tts.port import TTSError, TTSPort, TTSUnavailableError

SPEECH_PATH = "/audio/speech"

SUPPORTED_FORMATS = ("wav", "pcm")
WAV_FORMAT = "wav"
PCM_FORMAT = "pcm"


class OpenAICompatTTSAdapter(TTSPort):
    """Narration synthesis against a remote OpenAI-compatible endpoint."""

    def __init__(
        self,
        model: str,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = http.DEFAULT_TIMEOUT_SECONDS,
        response_format: str = WAV_FORMAT,
        pcm_sample_rate: int = 24000,
        pcm_channels: int = 1,
        pcm_sample_width: int = 2,
        transport: http.RawTransport | None = None,
    ) -> None:
        if not base_url:
            raise TTSError("base_url is required for a remote TTS adapter")
        if response_format not in SUPPORTED_FORMATS:
            raise TTSError(
                f"Unsupported response_format {response_format!r}; "
                f"expected one of {list(SUPPORTED_FORMATS)}"
            )
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._format = response_format
        self._pcm_sample_rate = pcm_sample_rate
        self._pcm_channels = pcm_channels
        self._pcm_sample_width = pcm_sample_width
        self._transport = transport

    @property
    def model(self) -> str:
        """Configured model identity."""
        return self._model

    @property
    def base_url(self) -> str:
        """Configured remote endpoint."""
        return self._base_url

    def synthesize(self, request: TTSRequest) -> SpeechAudio:
        """Send one narration request and return measured audio."""
        url = http.build_endpoint(self._base_url, SPEECH_PATH)
        payload: dict[str, object] = {
            "model": self._model,
            "input": request.text,
            "voice": request.voice,
            "speed": request.speed,
            "response_format": self._format,
        }
        try:
            body = http.post_for_bytes(
                url,
                payload,
                api_key=self._api_key,
                timeout=self._timeout,
                transport=self._transport,
            )
        except http.RemoteUnavailableError as exc:
            raise TTSUnavailableError(self._model, str(exc)) from exc
        except http.RemoteProtocolError as exc:
            raise TTSError(str(exc)) from exc

        if not body:
            raise TTSError(f"Remote TTS endpoint {url} returned no audio bytes")
        return self._measure(body, url)

    def _measure(self, body: bytes, url: str) -> SpeechAudio:
        """Derive duration from the bytes themselves."""
        if self._format == WAV_FORMAT:
            return _measure_wav(body, url)
        frame_bytes = self._pcm_channels * self._pcm_sample_width
        if frame_bytes <= 0:
            raise TTSError("pcm_channels and pcm_sample_width must be positive")
        frames = len(body) / frame_bytes
        return SpeechAudio(
            duration_seconds=frames / self._pcm_sample_rate,
            sample_rate=self._pcm_sample_rate,
            audio=body,
        )

    def unload(self) -> None:
        """No local weights are held; the remote host owns the model."""
        return None

    def available(self) -> bool:
        """True when the endpoint is configured well enough to attempt a call."""
        return bool(self._base_url and self._model)


def _measure_wav(body: bytes, url: str) -> SpeechAudio:
    """Read sample rate and frame count from a WAV header.

    The payload is passed through unchanged so downstream concatenation sees
    the exact bytes the server produced.
    """
    try:
        with wave.open(io.BytesIO(body), "rb") as handle:
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
    except (wave.Error, EOFError) as exc:
        raise TTSError(
            f"Remote TTS endpoint {url} did not return a readable WAV stream: {exc}"
        ) from exc

    if sample_rate <= 0 or frame_count <= 0:
        raise TTSError(
            f"Remote TTS endpoint {url} returned an empty WAV stream "
            f"(frames={frame_count}, rate={sample_rate})"
        )
    return SpeechAudio(
        duration_seconds=frame_count / sample_rate,
        sample_rate=sample_rate,
        audio=body,
    )
