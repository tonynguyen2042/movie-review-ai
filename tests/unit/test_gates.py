"""T068 acceptance: thresholds, duration gate, and lifecycle verdicts."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus, QualityMetric
from movie_review.jobs.manager import JobManager
from movie_review.jobs.state_machine import InvalidTransitionError, allowed, transition
from movie_review.pipeline.context import StageContext
from movie_review.quality.gates import (
    GateResult,
    QualityGateError,
    duration_metric,
    evaluate_gate,
    run_quality_gate,
)
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _metric(name: str, score: float) -> QualityMetric:
    return QualityMetric(name=name, score=score)


def test_duration_metric() -> None:
    assert duration_metric(1200.0, 1200.0).score == 100.0
    assert duration_metric(1176.0, 1200.0).score == pytest.approx(98.0)
    with pytest.raises(QualityGateError, match="Non-positive target"):
        duration_metric(10.0, 0.0)
    with pytest.raises(QualityGateError, match="Negative actual"):
        duration_metric(-1.0, 1200.0)


def test_evaluate_pass() -> None:
    result = evaluate_gate(
        [
            _metric("evidence_coverage", 96.0),
            _metric("timeline_consistency", 98.0),
            _metric("character_consistency", 97.0),
        ],
        1190.0,
        1200.0,
    )
    assert result.passed is True
    assert result.failures == []
    assert all(m.threshold > 0 for m in result.metrics if m.name != "duration_accuracy")


def test_evaluate_failures() -> None:
    result = evaluate_gate([_metric("evidence_coverage", 85.0)], 1190.0, 1200.0)
    assert result.passed is False
    assert result.failures == ["evidence_coverage"]


def test_evaluate_duration_failure() -> None:
    result = evaluate_gate([_metric("evidence_coverage", 100.0)], 1300.0, 1200.0)
    assert result.passed is False
    assert result.failures == ["duration_accuracy"]


@dataclass
class Harness:
    conn: sqlite3.Connection
    ctx: StageContext

    def gate(self, metrics: list[QualityMetric]) -> GateResult:
        return run_quality_gate(metrics, 1190.0, 1200.0, self.ctx)


def _harness__gates(tmp_path: Path) -> Harness:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
        JobStatus.VISUAL_ANALYSIS_READY,
        JobStatus.CHARACTERS_READY,
        JobStatus.EVENTS_READY,
        JobStatus.STORY_READY,
        JobStatus.REVIEW_PLAN_READY,
        JobStatus.SCRIPT_READY,
        JobStatus.SCRIPT_VERIFIED,
        JobStatus.AUDIO_READY,
        JobStatus.EDIT_PLAN_READY,
        JobStatus.RENDERED,
    ):
        manager.transition("job_1", state)
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )
    return Harness(conn=conn, ctx=ctx)


def _passing() -> list[QualityMetric]:
    return [
        _metric("evidence_coverage", 96.0),
        _metric("timeline_consistency", 98.0),
        _metric("character_consistency", 97.0),
    ]


def test_run_completes(tmp_path: Path) -> None:
    harness = _harness__gates(tmp_path)
    result = harness.gate(_passing())
    assert result.passed is True
    assert harness.ctx.manager.get("job_1").status is JobStatus.COMPLETED


def test_run_needs_review(tmp_path: Path) -> None:
    harness = _harness__gates(tmp_path)
    result = harness.gate([_metric("evidence_coverage", 10.0)])
    assert result.passed is False
    assert harness.ctx.manager.get("job_1").status is JobStatus.NEEDS_REVIEW


def test_run_unknown_job(tmp_path: Path) -> None:
    harness = _harness__gates(tmp_path)
    harness.ctx.job_id = "job_2"
    with pytest.raises(QualityGateError, match="Unknown job"):
        harness.gate(_passing())


def test_needs_review_terminal() -> None:
    job = Job(job_id="job_1", input_file="m.mp4", status=JobStatus.NEEDS_REVIEW)
    assert allowed(JobStatus.NEEDS_REVIEW) == frozenset()
    assert allowed(JobStatus.QUALITY_CHECKED) == frozenset(
        {JobStatus.COMPLETED, JobStatus.NEEDS_REVIEW, JobStatus.FAILED}
    )
    with pytest.raises(InvalidTransitionError):
        transition(job, JobStatus.COMPLETED)
