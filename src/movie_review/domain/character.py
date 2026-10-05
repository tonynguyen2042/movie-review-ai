"""Character model (spec FR-007; README section 16).

Unnamed characters use descriptive names (``"bartender"``); crowds and
background figures use ``"crowd"``/``"background"``. Identity linking happens
in T029; this model only carries discovery facts.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from movie_review.domain.evidence import Confidence


class Character(BaseModel):
    """One discovered character candidate or confirmed character."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    gender: str = "unknown"
    first_seen: float = Field(ge=0.0)
    last_seen: float = Field(ge=0.0)
    confidence: Confidence = 1.0
