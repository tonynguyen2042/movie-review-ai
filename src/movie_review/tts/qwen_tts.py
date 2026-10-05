"""Qwen3-TTS adapter implementing :class:`TTSPort` (T052, spec section 39).

Lazy audio-runtime loading; tests and non-MLX hosts inject a ``backend``
callable. Model and voice identities come from the caller (configured
``models.tts`` and style/CLI voice selection). Durations are measured from
returned PCM bytes, never trusted from metadata.
"""

from __future__ import annotations

from collections.abc import Callable

from movie_review.domain.tts import SpeechAudio, TTSRequest
from movie_review.tts.port import TTSError, TTSPort, TTSUnavailableError

RawBackend = Callable[[TTSRequest], tuple[bytes, int]]

_BYTES_PER_SAMPLE = 2


def _load_mlx_backend(model: str) -> RawBackend:
    """Build the real MLX audio backend or raise :class:`TTSUnavailableError`.

    NOTE: the ``mlx_audio`` call shape must be verified on Apple hardware
    during model benchmarking (T074); offline hosts always take the injected
    path.
    """
    try:
        import mlx_audio.tts as tts  # type: ignore[import-not-found]
    except ImportError as exc:
        raise TTSUnavailableError(model, "mlx-audio is not installed") from exc

    def _synthesize(request: TTSRequest) -> tuple[bytes, int]:
        result = tts.synthesize(
            request.text,
            model=model,
            voice=request.voice,
            emotion=request.emotion,
            speed=request.speed,
        )
        return bytes(result.audio), int(result.sample_rate)

    return _synthesize


class QwenTTSAdapter(TTSPort):
    """Qwen3-TTS family via MLX audio (model name supplied by caller)."""

    def __init__(self, model: str, backend: RawBackend | None = None) -> None:
        self._model = model
        self._backend = backend

    @property
    def model(self) -> str:
        """Configured model identity."""
        return self._model

    def _ensure_loaded(self) -> RawBackend:
        if self._backend is None:
            self._backend = _load_mlx_backend(self._model)
        return self._backend

    def synthesize(self, request: TTSRequest) -> SpeechAudio:
        try:
            pcm, sample_rate = self._ensure_loaded()(request)
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(f"TTS synthesis failed: {exc}") from exc
        if sample_rate <= 0:
            raise TTSError(f"Invalid sample rate: {sample_rate}")
        duration = len(pcm) / _BYTES_PER_SAMPLE / sample_rate
        return SpeechAudio(duration_seconds=duration, sample_rate=sample_rate, audio=pcm)

    def unload(self) -> None:
        """Drop the backend so its memory can be reclaimed (plan section 6)."""
        self._backend = None
        try:
            import mlx.core as mx  # type: ignore[import-not-found]

            mx.clear_cache()
        except ImportError:
            pass
