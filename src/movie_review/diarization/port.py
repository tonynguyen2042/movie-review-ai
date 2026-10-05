"""Diarization port: model-agnostic speaker segmentation contract (T020, P6).

Adapters (initial heuristic in T021, stronger models later) implement
:class:`DiarizationPort`. Character identity is resolved later (T029), never
here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from movie_review.domain.diarization import DiarizedSegment


class DiarizationError(Exception):
    """Base class for speaker segmentation failures."""


class DiarizationModelUnavailableError(DiarizationError):
    """The configured diarization model or runtime cannot be loaded here."""

    def __init__(self, model: str, detail: str = "") -> None:
        message = f"Diarization model unavailable: {model}"
        if detail:
            message += f": {detail}"
        super().__init__(message)
        self.model = model


class DiarizationPort(ABC):
    """Speech segmentation into anonymous speaker spans (spec section 14)."""

    @abstractmethod
    def diarize(self, audio_path: str | Path) -> list[DiarizedSegment]:
        """Segment audio into anonymous ``SPEAKER_00``-style spans in time order."""

    @abstractmethod
    def unload(self) -> None:
        """Release model resources (memory strategy, plan section 6)."""
