"""Evidence records backing AI claims (spec FR-010; README section 20)."""

from typing import Annotated

from pydantic import BaseModel, Field

from movie_review.domain.enums import EvidenceType

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class Evidence(BaseModel):
    """Traceable pointer from a claim to its source (dialogue, frame, scene...)."""

    id: str = Field(min_length=1)
    type: EvidenceType
    source_id: str = Field(min_length=1)
    start: float | None = Field(default=None, ge=0.0)
    end: float | None = Field(default=None, ge=0.0)
    confidence: Confidence = 1.0
