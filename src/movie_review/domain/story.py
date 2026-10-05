"""Story-level models: arcs, themes, twists (T036-T038).

Documentary structures persisted as JSON artifacts (relational queries do
not need them); the canonical export assembles them in T039.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from movie_review.domain.evidence import Confidence


class StoryElement(StrEnum):
    """Classical story structure elements (README section 23)."""

    SETUP = "SETUP"
    INCITING_INCIDENT = "INCITING_INCIDENT"
    FIRST_CONFLICT = "FIRST_CONFLICT"
    RISING_ACTION = "RISING_ACTION"
    MIDPOINT = "MIDPOINT"
    COMPLICATION = "COMPLICATION"
    CRISIS = "CRISIS"
    CLIMAX = "CLIMAX"
    RESOLUTION = "RESOLUTION"


class StoryArc(BaseModel):
    """One structural element with grounding; inapplicable when absent."""

    element: StoryElement
    applicable: bool = True
    description: str = ""
    event_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = 1.0


class Theme(BaseModel):
    """One extracted theme with grounding event references."""

    theme: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    confidence: Confidence = 1.0
