"""ASR port: model-agnostic speech recognition contract (T016, P6).

Adapters (Whisper MLX in T017, fakes in tests) implement :class:`ASRPort`.
Domain code depends only on this contract, never on model runtimes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from movie_review.domain.transcript import TranscriptSegment


class ASRError(Exception):
    """Base class for speech recognition failures."""


class ModelUnavailableError(ASRError):
    """The configured ASR model or runtime cannot be loaded here."""

    def __init__(self, model: str, detail: str = "") -> None:
        message = f"ASR model unavailable: {model}"
        if detail:
            message += f": {detail}"
        super().__init__(message)
        self.model = model


class ASRPort(ABC):
    """Speech-to-text with word/segment timestamps (spec section 13)."""

    @property
    def model(self) -> str:
        """Model identity used in cache keys.

        Concrete adapters override this with the configured checkpoint. The
        class-name fallback keeps the contract usable for test fakes without
        forcing them to invent a model name, but it is not a good cache key:
        two different checkpoints behind the same adapter would collide. Stages
        read this rather than inspecting adapter types, so a remote adapter
        contributes its real model id to cache identity.
        """
        return type(self).__name__

    @abstractmethod
    def transcribe(
        self, audio_path: str | Path, *, language: str | None = None
    ) -> list[TranscriptSegment]:
        """Transcribe audio; ``language`` None means auto-detect."""

    @abstractmethod
    def unload(self) -> None:
        """Release model resources (memory strategy, plan section 6)."""
