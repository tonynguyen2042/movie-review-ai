"""Review claims with verification status (spec FR-016/FR-017; README section 32)."""

from pydantic import BaseModel, Field

from movie_review.domain.enums import ClaimStatus, ClaimType
from movie_review.domain.evidence import Confidence


class Claim(BaseModel):
    """One checkable statement from a review script.

    New claims default to ``INSUFFICIENT_EVIDENCE``: no guessing (P1).
    """

    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    type: ClaimType
    evidence: list[str] = Field(default_factory=list)
    confidence: Confidence = 1.0
    status: ClaimStatus = ClaimStatus.INSUFFICIENT_EVIDENCE
