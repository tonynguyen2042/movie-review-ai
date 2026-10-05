"""Final quality gate: thresholds plus lifecycle verdict (T068, spec 69).

Critical gates: evidence_coverage >= 90, timeline_consistency >= 95,
character_consistency >= 95, duration error <= 2%. Any critical failure
marks the job NEEDS_REVIEW; otherwise COMPLETED. Thresholds are the gate's
contract (metric functions stay threshold-free).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from movie_review.domain import JobStatus, QualityMetric
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.context import StageContext
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "quality"
GATE_THRESHOLDS = {
    "evidence_coverage": 90.0,
    "timeline_consistency": 95.0,
    "character_consistency": 95.0,
}
MAX_DURATION_ERROR = 0.02


class QualityGateError(Exception):
    """Quality gating failed in a classified way."""


@dataclass(frozen=True)
class GateResult:
    """Gate verdict with stamped metrics."""

    passed: bool
    metrics: list[QualityMetric] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def duration_metric(actual_seconds: float, target_seconds: float) -> QualityMetric:
    """Duration accuracy 0-100 from relative error (spec: error <= 2%)."""
    if target_seconds <= 0:
        raise QualityGateError(f"Non-positive target: {target_seconds}")
    if actual_seconds < 0:
        raise QualityGateError(f"Negative actual duration: {actual_seconds}")
    error = abs(actual_seconds - target_seconds) / target_seconds
    return QualityMetric(
        name="duration_accuracy",
        score=max(0.0, 100.0 * (1.0 - error)),
        detail=f"error {error:.4f}",
    )


def evaluate_gate(
    metrics: list[QualityMetric], actual_seconds: float, target_seconds: float
) -> GateResult:
    """Stamp thresholds and decide pass/fail (no lifecycle changes)."""
    stamped = [
        QualityMetric(
            name=metric.name,
            score=metric.score,
            threshold=GATE_THRESHOLDS.get(metric.name, metric.threshold),
            detail=metric.detail,
        )
        for metric in metrics
    ]
    stamped.append(duration_metric(actual_seconds, target_seconds))
    failures = [
        metric.name for metric in stamped if metric.name in GATE_THRESHOLDS and not metric.passed
    ]
    duration = next(m for m in stamped if m.name == "duration_accuracy")
    error = 1.0 - duration.score / 100.0
    if error > MAX_DURATION_ERROR:
        failures.append("duration_accuracy")
    return GateResult(passed=not failures, metrics=stamped, failures=failures)


def run_quality_gate(
    metrics: list[QualityMetric],
    actual_seconds: float,
    target_seconds: float,
    ctx: StageContext,
) -> GateResult:
    """Evaluate gates for a job through to COMPLETED or NEEDS_REVIEW."""
    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise QualityGateError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise QualityGateError(f"Job {ctx.job_id} failed; resume arrives in T085")
    owns_completion = job.status is JobStatus.RENDERED

    result = evaluate_gate(metrics, actual_seconds, target_seconds)
    duration_ms = int((time.perf_counter() - started) * 1000)
    with ulog.logging_context(job_id=ctx.job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="stage.completed",
            status="ok",
            duration_ms=duration_ms,
            passed=result.passed,
        )
    if owns_completion:
        ctx.manager.transition(ctx.job_id, JobStatus.QUALITY_CHECKED)
        ctx.manager.transition(
            ctx.job_id,
            JobStatus.COMPLETED if result.passed else JobStatus.NEEDS_REVIEW,
        )
    return result
