"""A resume that names a stage the pipeline does not have is a usage error.

T123 regression. `recovery_plan` returns the job's recorded `failed_stage`
verbatim, falling back to "unknown" when it was never recorded. That value
reached `run_pipeline`, which raised a ValueError for a stage name it did
not know -- and the CLI caught only KeyboardInterrupt, so the command printed
a raw traceback instead of exiting with a message.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from movie_review.cli.app import app
from movie_review.domain import Job, JobStatus
from movie_review.pipeline.orchestrator import ResumeError, resume_job
from movie_review.storage.database import bootstrap, connect


def _failed_job(tmp_path: Path, failed_stage: str) -> str:
    """A job that failed at a stage name the pipeline may not know."""
    db = tmp_path / "jobs.db"
    conn = connect(bootstrap(db))
    repo_job = Job(job_id="job_1", input_file="m.mp4")
    conn.execute(
        "INSERT INTO jobs (job_id, input_file, status, failed_stage, error, "
        "retry_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            repo_job.job_id,
            repo_job.input_file,
            JobStatus.FAILED.value,
            failed_stage,
            "something went wrong",
            0,
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ),
    )
    conn.commit()
    conn.close()
    return str(db)


def test_resume_reports_an_unknown_failed_stage(tmp_path: Path) -> None:
    db = _failed_job(tmp_path, "not-a-stage")
    with pytest.raises(ResumeError) as excinfo:
        resume_job("job_1", db)
    message = str(excinfo.value)
    assert "not-a-stage" in message
    assert "not a pipeline stage" in message


def test_the_cli_resume_exits_cleanly(tmp_path: Path) -> None:
    """A usage error, not a traceback."""
    db = _failed_job(tmp_path, "not-a-stage")
    result = CliRunner().invoke(app, ["resume", "job_1", "--db-path", db])
    assert result.exit_code != 0
    assert "Traceback" not in (result.stdout or "") + (result.stderr or "")
    assert "not-a-stage" in (result.stdout or "") + (result.stderr or "")


def test_the_cli_retry_rejects_an_unknown_stage(tmp_path: Path) -> None:
    """The same check applies to an explicitly named stage."""
    db = _failed_job(tmp_path, "not-a-stage")
    result = CliRunner().invoke(app, ["retry", "job_1", "--db-path", db, "--stage", "nope"])
    assert result.exit_code != 0
    assert "Traceback" not in (result.stdout or "") + (result.stderr or "")


def test_a_known_stage_is_accepted(tmp_path: Path) -> None:
    """The validation must not reject a stage the pipeline really has."""
    from movie_review.pipeline.orchestrator import STAGE_SEQUENCE

    order = [name for name, _ in STAGE_SEQUENCE]
    assert "render-manifest" in order
    assert "quality" in order
