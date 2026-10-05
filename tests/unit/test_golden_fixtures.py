"""T078 acceptance: golden fixtures are deterministic and well-formed."""

from movie_review.eval.fixtures import golden_analysis, golden_claims


def test_golden_analysis_shape() -> None:
    doc = golden_analysis()
    for key in ("movie", "scenes", "characters", "events", "evidence", "timeline"):
        assert key in doc
    assert golden_analysis() == golden_analysis()


def test_golden_claims_verdicts() -> None:
    claims = golden_claims()
    assert {claim["verdict"] for claim in claims} == {"SUPPORTED", "INSUFFICIENT_EVIDENCE"}
