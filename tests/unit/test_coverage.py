"""T064 acceptance: evidence coverage scoring."""

from movie_review.domain import Claim, ClaimStatus, ClaimType
from movie_review.quality.coverage import evidence_coverage


def _claim__coverage(claim_id: str, type: ClaimType, status: ClaimStatus) -> Claim:
    return Claim(
        claim_id=claim_id,
        text="Statement here.",
        type=type,
        evidence=["e1"],
        confidence=0.9,
        status=status,
    )


def test_full_coverage() -> None:
    metric = evidence_coverage([_claim__coverage("c1", ClaimType.PLOT_FACT, ClaimStatus.SUPPORTED)])
    assert metric.name == "evidence_coverage"
    assert metric.score == 100.0


def test_partial_coverage_ignores_opinion() -> None:
    claims = [
        _claim__coverage("c1", ClaimType.PLOT_FACT, ClaimStatus.SUPPORTED),
        _claim__coverage("c2", ClaimType.PLOT_FACT, ClaimStatus.SUPPORTED),
        _claim__coverage("c3", ClaimType.PLOT_FACT, ClaimStatus.PARTIALLY_SUPPORTED),
        _claim__coverage("c4", ClaimType.PLOT_FACT, ClaimStatus.INSUFFICIENT_EVIDENCE),
        _claim__coverage("c5", ClaimType.OPINION, ClaimStatus.SUPPORTED),
    ]
    metric = evidence_coverage(claims)
    assert metric.score == 50.0
    assert "2/4" in metric.detail


def test_vacuous_coverage() -> None:
    assert evidence_coverage([]).score == 100.0
    assert (
        evidence_coverage([_claim__coverage("c1", ClaimType.OPINION, ClaimStatus.SUPPORTED)]).score
        == 100.0
    )
