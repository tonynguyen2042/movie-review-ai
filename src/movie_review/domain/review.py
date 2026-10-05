"""Review plan and script contracts (T041 outline; T044 script models follow)."""

from __future__ import annotations

from pydantic import BaseModel, Field, PositiveInt


class OutlineSection(BaseModel):
    """One planned review section (spec section 27)."""

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    target_seconds: PositiveInt
    event_ids: list[str] = Field(default_factory=list)
    purpose: str = ""


class ReviewPlan(BaseModel):
    """Structured review outline preceding prose generation."""

    sections: list[OutlineSection] = Field(min_length=1)
    total_seconds: PositiveInt
