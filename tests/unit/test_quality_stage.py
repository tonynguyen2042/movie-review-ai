"""The quality gate must be able to fail a job.

T118 regression. The quality stage computed no metrics at all and compared
the target duration with itself, so `evaluate_gate` had nothing to fail and
every job reached COMPLETED. The three critical thresholds in
`quality/gates.py` -- evidence coverage 90, timeline consistency 95 and
character consistency 95 -- were never consulted, and no quality report was
ever written.

These tests drive the stage the way the pipeline drives it and assert that a
job which does not meet the thresholds ends in NEEDS_REVIEW.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import (
    Claim,
    ClaimStatus,
    ClaimType,
    Event,
    EventType,
    Job,
    JobStatus,
    Scene,
)
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.orchestrator import PipelineContext, _get_stage_function
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect

LIFECYCLE = (
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
)


def _write_wav__quality_stage(path: Path, seconds: float, rate: int = 8000) -> None:
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * int(rate * seconds))


def _harness__quality_stage(tmp_path: Path) -> tuple[PipelineContext, sqlite3.Connection]:
    """A job that reached RENDERED, with a scene, an event and a claim."""
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    for state in LIFECYCLE:
        manager.transition("job_1", state)

    repo.save_scene(
        conn, "job_1", Scene(scene_id="scene_000001", start=0.0, end=60.0, duration=60.0)
    )
    repo.save_event(
        conn,
        "job_1",
        Event(
            id="event_00001",
            type=EventType.DISCOVERY,
            timestamp=10.0,
            characters=[],
            location="loc_01",
            description="Someone finds something.",
            importance=0.9,
            evidence=[],
        ),
    )

    ctx = PipelineContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
        movie_path=tmp_path / "movie.mp4",
    )
    return ctx, conn


def test_the_quality_stage_fails_a_job_that_misses_its_target(tmp_path: Path) -> None:
    """Regression: every job passed, because the duration was compared with itself."""
    ctx, conn = _harness__quality_stage(tmp_path)
    # Sixty seconds of narration for a twenty-minute target: a job that is
    # nowhere near the length it promised.
    _write_wav__quality_stage(ctx.jobs_dir / "job_1" / "tts" / "narration.wav", 60.0)

    stage = _get_stage_function("quality")
    assert stage is not None
    gate = stage(ctx)

    assert gate.passed is False
    assert "duration_accuracy" in gate.failures
    assert ctx.manager.get("job_1").status is JobStatus.NEEDS_REVIEW


def test_the_quality_stage_reports_the_metrics_it_computed(tmp_path: Path) -> None:
    """The gate must see the three metrics its thresholds name."""
    ctx, conn = _harness__quality_stage(tmp_path)
    _write_wav__quality_stage(ctx.jobs_dir / "job_1" / "tts" / "narration.wav", 60.0)

    stage = _get_stage_function("quality")
    assert stage is not None
    gate = stage(ctx)

    names = {metric.name for metric in gate.metrics}
    assert "evidence_coverage" in names
    assert "timeline_consistency" in names
    assert "character_consistency" in names
    assert "duration_accuracy" in names


def test_an_unsupported_claim_fails_the_evidence_gate(tmp_path: Path) -> None:
    """A claim that is not supported must drag the coverage score down."""
    ctx, conn = _harness__quality_stage(tmp_path)
    # A narration as long as the target, so the duration gate is not what
    # fails: the evidence gate is.
    _write_wav__quality_stage(ctx.jobs_dir / "job_1" / "tts" / "narration.wav", 1200.0)
    repo.save_claim(
        conn,
        "job_1",
        Claim(
            claim_id="claim_001",
            type=ClaimType.PLOT_FACT,
            text="The hero finds the photograph.",
            status=ClaimStatus.INSUFFICIENT_EVIDENCE,
            evidence=[],
        ),
    )

    stage = _get_stage_function("quality")
    assert stage is not None
    gate = stage(ctx)

    coverage = next(m for m in gate.metrics if m.name == "evidence_coverage")
    assert coverage.score == 0.0
    assert "evidence_coverage" in gate.failures
    assert ctx.manager.get("job_1").status is JobStatus.NEEDS_REVIEW


def test_the_quality_report_is_written(tmp_path: Path) -> None:
    """The report is the artifact of record for the gate's verdict."""
    ctx, conn = _harness__quality_stage(tmp_path)
    _write_wav__quality_stage(ctx.jobs_dir / "job_1" / "tts" / "narration.wav", 1200.0)

    stage = _get_stage_function("quality")
    assert stage is not None
    stage(ctx)

    report_path = ctx.jobs_dir / "job_1" / "qc" / "quality-report.json"
    assert report_path.is_file()
    document = artifacts.read_json(report_path)
    assert document["job_id"] == "job_1"
    assert document["gate"]["passed"] is True
    assert {m["name"] for m in document["metrics"]} >= {
        "evidence_coverage",
        "timeline_consistency",
        "character_consistency",
        "duration_accuracy",
    }
    assert repo.get_artifact(conn, "job_1-quality-report") is not None
