"""Visual planning and render contracts (T056 plan, T057 ranges, T058 manifest)."""

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


class ManifestSegment(BaseModel):
    """One render timeline segment (spec section 44)."""

    paragraph_id: str = Field(min_length=1)
    start: float = Field(ge=0.0)
    duration: float = Field(gt=0.0)
    scene_id: str = Field(min_length=1)
    clip_start: float = Field(ge=0.0)
    clip_end: float = Field(gt=0.0)
    loop_clip: bool = False


class RenderManifest(BaseModel):
    """Assembled render timeline with totals."""

    segments: list[ManifestSegment] = Field(min_length=1)
    total_seconds: float = Field(gt=0.0)
    source_seconds: float = Field(ge=0.0)
