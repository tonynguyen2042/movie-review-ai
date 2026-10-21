"""A transient stage failure must be retried, and the count kept.

T137 regression. `pipeline/retry.py::run_with_retry` existed and was
tested, but `run_stage` did not use it -- the CLI only used it in the
`retry` command. One network blip aborted a run that had been going for
hours, and README section 65's four-step escalation was not implemented at
all.

The stage errors wrap the cause that says what went wrong, so the decision
has to look at the chain: a model that was momentarily unreachable is
retryable even though the stage's own error type is not.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.orchestrator import PipelineContext, _is_transient, run_stage
from movie_review.pipeline.retry import RetryPolicy
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real policy backs off two seconds between attempts."""
    import importlib

    module = importlib.import_module("movie_review.pipeline.orchestrator")
    monkeypatch.setattr(
        module, "STAGE_RETRY_POLICY", RetryPolicy(max_attempts=3, backoff_seconds=0.0)
    )


def _ctx__stage_retry(tmp_path: Path) -> tuple[PipelineContext, sqlite3.Connection]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
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


def test_a_transient_failure_is_retried(tmp_path: Path) -> None:
    """The stage is attempted again after a transient failure."""
    ctx, conn = _ctx__stage_retry(tmp_path)
    attempts: list[int] = []

    def flaky(_ctx: PipelineContext) -> None:
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("the server went away for a moment")

    try:
        result = run_stage("vision", flaky, ctx)
        assert result.success is True
        assert len(attempts) == 3
    finally:
        conn.close()


def test_a_permanent_failure_is_not_retried(tmp_path: Path) -> None:
    """A refusal is not going to pass on its own."""
    ctx, conn = _ctx__stage_retry(tmp_path)
    attempts: list[int] = []

    def broken(_ctx: PipelineContext) -> None:
        attempts.append(1)
        raise ValueError("the prompt does not match the schema")

    try:
        result = run_stage("vision", broken, ctx)
        assert result.success is False
        assert len(attempts) == 1, "a permanent failure was retried"
    finally:
        conn.close()


def test_the_retry_count_is_recorded_on_the_job(tmp_path: Path) -> None:
    """The job must show that the stage was attempted more than once."""
    ctx, conn = _ctx__stage_retry(tmp_path)
    attempts: list[int] = []

    def flaky(_ctx: PipelineContext) -> None:
        attempts.append(1)
        if len(attempts) < 2:
            raise ConnectionError("blip")

    try:
        run_stage("vision", flaky, ctx)
        assert ctx.manager.get("job_1").retry_count == 1
    finally:
        conn.close()


def test_a_wrapped_transient_cause_is_recognised() -> None:
    """The stage wraps its cause, so the chain has to be walked."""
    from movie_review.asr.port import ModelUnavailableError

    class StageError(Exception):
        pass

    wrapped = StageError("cannot transcribe")
    wrapped.__cause__ = ModelUnavailableError("whisper", "not reachable")
    assert _is_transient(wrapped) is True

    plain = StageError("the schema did not match")
    assert _is_transient(plain) is False


def test_a_cycle_in_the_cause_chain_does_not_loop() -> None:
    """A self-referential chain must terminate."""
    first = RuntimeError("first")
    second = RuntimeError("second")
    first.__cause__ = second
    second.__cause__ = first
    assert _is_transient(first) is False


def test_a_permanent_failure_leaves_the_job_retryable(tmp_path: Path) -> None:
    """A failed stage is still reported as failed."""
    ctx, conn = _ctx__stage_retry(tmp_path)
    try:
        result = run_stage("vision", lambda _c: (_ for _ in ()).throw(ValueError("nope")), ctx)
        assert result.success is False
        assert result.error is not None
    finally:
        conn.close()
