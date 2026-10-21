"""T081 acceptance: hallucination rate flags unsupported major claims."""

from movie_review.eval.hallucination import evaluate_hallucinations


def _claim__hallucination(cid: str, ctype: str, verdict: str) -> dict[str, str]:
    return {"claim_id": cid, "type": ctype, "verdict": verdict}


def test_hallucination_clean_passes() -> None:
    report = evaluate_hallucinations([_claim__hallucination("c1", "PLOT_FACT", "SUPPORTED")])
    assert report.passed and report.rate == 0.0


def test_hallucination_flags_unsupported_major() -> None:
    claims = [_claim__hallucination(f"c{i}", "PLOT_FACT", "SUPPORTED") for i in range(98)]
    claims.append(_claim__hallucination("bad1", "PLOT_FACT", "CONTRADICTED"))
    claims.append(_claim__hallucination("bad2", "TIMELINE_FACT", "INSUFFICIENT_EVIDENCE"))
    report = evaluate_hallucinations(claims)
    assert not report.passed
    assert report.unsupported_ids == ["bad1", "bad2"]


def test_hallucination_ignores_opinion() -> None:
    report = evaluate_hallucinations(
        [_claim__hallucination("o1", "OPINION", "INSUFFICIENT_EVIDENCE")]
    )
    assert report.major_total == 0 and report.passed
