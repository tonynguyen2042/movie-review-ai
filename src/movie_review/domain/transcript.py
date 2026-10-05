"""Transcript segment model (spec section 13)."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from movie_review.domain.evidence import Confidence


class TranscriptSegment(BaseModel):
    """One timestamped ASR segment. Empty text is allowed (silence/noise)."""

    segment_id: str = Field(min_length=1)
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str = ""
    language: str | None = None
    confidence: Confidence = 1.0

    @model_validator(mode="after")
    def _check_span(self) -> TranscriptSegment:
        if self.end < self.start:
            raise ValueError("segment end must not precede start")
        return self
