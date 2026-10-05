"""T082 acceptance: evidence coverage evaluation enforces the 90% target."""

from movie_review.eval.coverage_eval import evaluate_coverage


def test_coverage_full_passes() -> None:
    claims = [{"claim_id": "c1", "type": "PLOT_FACT", "evidence": ["ev1"]}]
    report = evaluate_coverage(claims, ["ev1", "ev2"])
    assert report.passed and report.coverage == 100.0


def test_coverage_low_fails() -> None:
    claims = [{"claim_id": f"c{i}", "type": "PLOT_FACT", "evidence": ["ev1"]} for i in range(8)] + [
        {"claim_id": "bare1", "type": "PLOT_FACT", "evidence": []},
        {"claim_id": "bare2", "type": "PLOT_FACT", "evidence": []},
    ]
    report = evaluate_coverage(claims, ["ev1"])
    assert not report.passed
    assert report.coverage == 80.0


def test_coverage_ignores_opinion() -> None:
    report = evaluate_coverage([{"claim_id": "o", "type": "OPINION", "evidence": []}], [])
    assert report.major_total == 0 and report.passed
