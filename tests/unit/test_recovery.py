"""T072 acceptance: restart points from persisted job state."""

from pathlib import Path

import pytest

from movie_review.domain import Job, JobStatus
from movie_review.jobs.manager import JobManager
from movie_review.jobs.recovery import RecoveryPlan, recovery_plan
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from tests.helpers import (
    _manager,
)


def _at(manager: JobManager, *states: JobStatus) -> Job:
    job = manager.create("m.mp4")
    for state in states:
        manager.transition(job.job_id, state)
    return manager.get(job.job_id)


def test_mid_pipeline_mapping(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    assert recovery_plan(manager, _at(manager, JobStatus.INGESTING).job_id).resume_stage == "ingest"
    assert (
        recovery_plan(
            manager, _at(manager, JobStatus.INGESTING, JobStatus.MEDIA_READY).job_id
        ).resume_stage
        == "scenes"
    )
    assert (
        recovery_plan(
            manager,
            _at(manager, JobStatus.INGESTING, JobStatus.MEDIA_READY, JobStatus.SCENES_READY).job_id,
        ).resume_stage
        == "transcript"
    )


def test_failed_resumes_failed_stage(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    job = manager.create("m.mp4")
    manager.transition(job.job_id, JobStatus.INGESTING)
    manager.fail(job.job_id, "ingest", "unreadable")
    plan = recovery_plan(manager, job.job_id)
    assert isinstance(plan, RecoveryPlan)
    assert plan.resume_stage == "ingest"
    assert "unreadable" in plan.reason


def test_terminal_states(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="done", input_file="m", status=JobStatus.COMPLETED))
    assert recovery_plan(manager, "done").resume_stage == "done"
    repo.save_job(conn, Job(job_id="review", input_file="m", status=JobStatus.NEEDS_REVIEW))
    assert recovery_plan(manager, "review").resume_stage == "manual"
    conn.close()


def test_unknown_job(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    with pytest.raises(JobNotFoundError):
        recovery_plan(manager, "job_20990101_001")
