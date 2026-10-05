"""Review plan and script contracts (T041 outline; T044 script models follow)."""

from __future__ import annotations

from pydantic import BaseModel, Field, PositiveInt

from movie_review.domain.claim import Claim


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


class ReviewParagraph(BaseModel):
    """One narratable paragraph with tracked claims (spec section 31)."""

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    target_seconds: PositiveInt
    claims: list[Claim] = Field(default_factory=list)
    visual_intent: str = ""


class ReviewSection(BaseModel):
    """One script section of paragraphs."""

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    paragraphs: list[ReviewParagraph] = Field(min_length=1)


class ReviewScript(BaseModel):
    """Primary script representation; Markdown renders from this (spec 31)."""

    sections: list[ReviewSection] = Field(min_length=1)
