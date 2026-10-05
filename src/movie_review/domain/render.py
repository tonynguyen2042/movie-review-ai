"""Visual planning and render contracts (T056 plan; T057-T058 extend)."""

from __future__ import annotations

from pydantic import BaseModel, Field, PositiveInt


class PlannedClip(BaseModel):
    """One candidate scene illustrating a paragraph, ranked by priority."""

    paragraph_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    priority: PositiveInt = 1
    reason: str = ""


class VisualPlan(BaseModel):
    """Paragraph-to-scene mapping; exact ranges arrive in T057."""

    paragraph_clips: list[PlannedClip] = Field(default_factory=list)
