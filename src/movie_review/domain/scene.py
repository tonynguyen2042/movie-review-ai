"""Scene timeline model with stable IDs (spec FR-002; README section 11)."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class Scene(BaseModel):
    """One detected scene. ``end`` must follow ``start``; ``duration`` must agree."""

    scene_id: str = Field(min_length=1)
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    duration: float = Field(ge=0.0)
    shot_count: int = Field(default=0, ge=0)
    cut_density: float = Field(default=0.0, ge=0.0)
    motion_score: float = Field(default=0.0, ge=0.0)
    brightness: float = Field(default=0.0, ge=0.0)
    audio_energy: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def _check_chronology(self) -> Scene:
        if self.end <= self.start:
            raise ValueError("scene end must be after start")
        if abs(self.duration - (self.end - self.start)) > 1e-3:
            raise ValueError("scene duration must match end - start")
        return self
