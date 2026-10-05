"""Location model (movie knowledge base entity)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from movie_review.domain.evidence import Confidence


class Location(BaseModel):
    """One canonical location observed across scenes."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    first_seen: float = Field(ge=0.0)
    last_seen: float = Field(ge=0.0)
    confidence: Confidence = 1.0
