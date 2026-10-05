"""Story event model (spec FR-009; README sections 18-19).

An event is a meaningful story state change (a discovery, not a footstep).
Extraction happens in T033; this module is only the contract.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from movie_review.domain.evidence import Confidence


class EventType(StrEnum):
    """Story event categories."""

    INTRODUCTION = "INTRODUCTION"
    MEETING = "MEETING"
    DISCOVERY = "DISCOVERY"
    CONFLICT = "CONFLICT"
    DECISION = "DECISION"
    BETRAYAL = "BETRAYAL"
    REVELATION = "REVELATION"
    ACTION = "ACTION"
    DEATH = "DEATH"
    ESCAPE = "ESCAPE"
    CAPTURE = "CAPTURE"
    ROMANCE = "ROMANCE"
    INVESTIGATION = "INVESTIGATION"
    DECEPTION = "DECEPTION"
    FLASHBACK = "FLASHBACK"
    FLASH_FORWARD = "FLASH_FORWARD"
    TRANSITION = "TRANSITION"
    CLIMAX = "CLIMAX"
    RESOLUTION = "RESOLUTION"
    OTHER = "OTHER"


class Event(BaseModel):
    """One story state change with evidence links."""

    id: str = Field(min_length=1)
    type: EventType
    timestamp: float = Field(ge=0.0)
    characters: list[str] = Field(default_factory=list)
    location: str | None = None
    description: str = Field(min_length=1)
    importance: Confidence = 0.5
    evidence: list[str] = Field(default_factory=list)
