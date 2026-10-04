"""T006 acceptance: valid lifecycle transitions, invalid ones rejected."""

from pathlib import Path

import pytest

from movie_review.domain import Job, JobStatus
from movie_review.jobs.manager import JobManager
from movie_review.jobs.state_machine import (
    InvalidTransitionError,
    JobNotFoundError,
    allowed,
    transition,
)
from movie_review.storage import connect
from movie_review.storage.database import bootstrap


def test_full_pipeline_chain_walks() -> None:
    job = Job(job_id="j", input_file="m.mp4")
    chain = [
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
        JobStatus.QUALITY_CHECKED,
        JobStatus.COMPLETED,
    ]
    for state in chain:
        job = transition(job, state)
    assert job.status == JobStatus.COMPLETED


def test_skip_ahead_rejected() -> None:
    job = Job(job_id="j", input_file="m.mp4")
    with pytest.raises(InvalidTransitionError):
        transition(job, JobStatus.SCRIPT_READY)


def test_failed_reachable_from_anywhere_and_terminal() -> None:
    job = Job(job_id="j", input_file="m.mp4")
    failed = transition(job, JobStatus.FAILED, failed_stage="ingest", error="nope")
    assert failed.failed_stage == "ingest"
    assert failed.error == "nope"
    assert allowed(JobStatus.FAILED) == frozenset()
    with pytest.raises(InvalidTransitionError):
        transition(failed, JobStatus.INGESTING)


def test_failed_requires_cause() -> None:
    job = Job(job_id="j", input_file="m.mp4")
    with pytest.raises(InvalidTransitionError):
        transition(job, JobStatus.FAILED)


def test_completed_is_terminal() -> None:
    job = Job(job_id="j", input_file="m.mp4", status=JobStatus.COMPLETED)
    with pytest.raises(InvalidTransitionError):
        transition(job, JobStatus.FAILED)


def _manager(tmp_path: Path) -> JobManager:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    return JobManager(conn)


def test_manager_create_persists(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    job = manager.create("movie.mp4")
    assert job.job_id.startswith("job_")
    assert manager.get(job.job_id) == job


def test_manager_ids_unique(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    first = manager.create("a.mp4")
    second = manager.create("b.mp4")
    assert first.job_id != second.job_id


def test_manager_transition_persists(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    job = manager.create("movie.mp4")
    advanced = manager.transition(job.job_id, JobStatus.INGESTING)
    assert advanced.status == JobStatus.INGESTING
    assert manager.get(job.job_id).status == JobStatus.INGESTING
    with pytest.raises(InvalidTransitionError):
        manager.transition(job.job_id, JobStatus.SCRIPT_READY)


def test_manager_fail_records_cause(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    job = manager.create("movie.mp4")
    failed = manager.fail(job.job_id, stage="ingest", error="unreadable")
    assert failed.status == JobStatus.FAILED
    assert failed.failed_stage == "ingest"
    assert failed.error == "unreadable"
    assert manager.get(job.job_id).failed_stage == "ingest"


def test_manager_unknown_job(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    with pytest.raises(JobNotFoundError):
        manager.get("job_20990101_001")
    with pytest.raises(JobNotFoundError):
        manager.transition("job_20990101_001", JobStatus.INGESTING)


def test_manager_shares_connection_state(tmp_path: Path) -> None:
    path = bootstrap(tmp_path / "jobs.db")
    first = JobManager(connect(path)).create("movie.mp4")
    second = JobManager(connect(path))
    assert second.get(first.job_id) == first
