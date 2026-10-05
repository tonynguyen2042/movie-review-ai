"""Diarization models (spec section 14).

Speakers are anonymous labels (``SPEAKER_00``); identity resolution happens
later (T029). Labels are never invented outside the diarization adapter.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class DiarizedSegment(BaseModel):
    """One speaker-homogeneous speech span."""

    speaker: str = Field(pattern=r"^SPEAKER_\d+$")
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _check_span(self) -> DiarizedSegment:
        if self.end < self.start:
            raise ValueError("segment end must not precede start")
        return self
