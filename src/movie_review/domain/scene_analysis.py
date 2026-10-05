"""Scene visual analysis model (spec section 15).

Produced by the VLM port from keyframes plus story context. Lists are
observed entities only — interpretation belongs to later story stages.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from movie_review.domain.evidence import Confidence


class SceneAnalysis(BaseModel):
    """Structured visual understanding of one scene."""

    scene_id: str = Field(min_length=1)
    location: str = ""
    characters: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    emotions: list[str] = Field(default_factory=list)
    visual_events: list[str] = Field(default_factory=list)
    importance: Confidence = 0.5
    confidence: Confidence = 1.0
