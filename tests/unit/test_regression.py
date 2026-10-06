"""T083 acceptance: regression runner aggregates golden evaluators."""

from movie_review.eval.regression import run_regression


def test_regression_passes_on_golden() -> None:
    claims = [{"claim_id": "c1", "type": "PLOT_FACT", "evidence": ["ev1"], "verdict": "SUPPORTED"}]
    report = run_regression(["e_escape"], ["e_escape"], claims, ["ev1"])
    assert report.passed and report.plot_f1 == 1.0


def test_regression_fails_on_bad_predictions() -> None:
    report = run_regression(["e_wrong"], ["e_escape"], [], [])
    assert not report.passed
    assert any("plot_f1" in failure for failure in report.failures)
