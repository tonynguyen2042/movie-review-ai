"""TTS port: model-agnostic narration synthesis contract (T051, P6).

Adapters (Qwen3-TTS in T052, fakes in tests) implement :class:`TTSPort`.
Chunking (T053) and concatenation (T054) build on this contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from movie_review.domain.tts import SpeechAudio, TTSRequest


class TTSError(Exception):
    """Base class for speech synthesis failures."""


class TTSUnavailableError(TTSError):
    """The configured TTS model or runtime cannot be loaded here."""

    def __init__(self, model: str, detail: str = "") -> None:
        message = f"TTS model unavailable: {model}"
        if detail:
            message += f": {detail}"
        super().__init__(message)
        self.model = model


class TTSPort(ABC):
    """Paragraph-to-audio narration synthesis (spec section 39)."""

    @property
    def model(self) -> str:
        """Model identity recorded alongside synthesized narration.

        See :attr:`movie_review.asr.port.ASRPort.model`; concrete adapters
        override it with the configured checkpoint.
        """
        return type(self).__name__

    @abstractmethod
    def synthesize(self, request: TTSRequest) -> SpeechAudio:
        """Synthesize one request; voice/emotion/speed come from the caller."""

    @abstractmethod
    def unload(self) -> None:
        """Release model resources (memory strategy, plan section 6)."""
