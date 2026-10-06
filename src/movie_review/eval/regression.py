"""Golden regression test runner (T083).

Runs the golden evaluators (plot accuracy, hallucinations, coverage)
over fixture predictions and aggregates pass/fail. Used in CI to block
regressions in story understanding without loading models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from movie_review.eval.accuracy import plot_accuracy
from movie_review.eval.coverage_eval import evaluate_coverage
from movie_review.eval.hallucination import evaluate_hallucinations

MIN_PLOT_F1 = 0.8


@dataclass(frozen=True)
class RegressionReport:
    """Aggregated golden evaluation verdict."""

    plot_f1: float
    hallucination_rate: float
    coverage: float
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def run_regression(
    predicted_event_ids: list[str],
    expected_event_ids: list[str],
    claims: list[dict[str, Any]],
    evidence_ids: list[str],
) -> RegressionReport:
    """Run all golden evaluators and aggregate failures."""
    failures: list[str] = []
    accuracy = plot_accuracy(predicted_event_ids, expected_event_ids)
    if accuracy.f1 < MIN_PLOT_F1:
        failures.append(f"plot_f1 {accuracy.f1:.3f} < {MIN_PLOT_F1}")
    hallucinations = evaluate_hallucinations(claims)
    if not hallucinations.passed:
        failures.append(f"hallucination rate {hallucinations.rate:.4f} too high")
    coverage = evaluate_coverage(claims, evidence_ids)
    if not coverage.passed:
        failures.append(f"coverage {coverage.coverage:.1f} < 90")
    return RegressionReport(
        plot_f1=accuracy.f1,
        hallucination_rate=hallucinations.rate,
        coverage=coverage.coverage,
        failures=failures,
    )
