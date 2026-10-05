"""Evidence coverage metric (T064, spec gate >= 90).

Share of factual claims carrying a SUPPORTED verdict, as a 0-100 score.
Vacuously 100 when no factual claims exist.
"""

from __future__ import annotations

from movie_review.domain import Claim, ClaimStatus, ClaimType, QualityMetric

NON_FACTUAL = frozenset({ClaimType.INTERPRETATION, ClaimType.OPINION, ClaimType.THEME})


def evidence_coverage(claims: list[Claim]) -> QualityMetric:
    """Score factual-claim support from T047 verdicts."""
    factual = [claim for claim in claims if claim.type not in NON_FACTUAL]
    if not factual:
        return QualityMetric(name="evidence_coverage", score=100.0, detail="no factual claims")
    supported = sum(1 for claim in factual if claim.status is ClaimStatus.SUPPORTED)
    score = supported / len(factual) * 100.0
    return QualityMetric(
        name="evidence_coverage",
        score=score,
        detail=f"{supported}/{len(factual)} factual claims supported",
    )
