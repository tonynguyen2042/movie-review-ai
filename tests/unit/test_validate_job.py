"""`movie-review validate` must actually validate something (T108).

It could not. Three defects compounded:

- It derived the files to check from the job status, so it verified whatever it
  guessed rather than what the run produced. A job that had only ever run ingest
  was checked for scenes.json and transcript.json.
- The jobs directory was off by one level: it looked under ``<data>/<job_id>/``
  while every stage writes to ``<data>/jobs/<job_id>/``.
- Every expected hash was the empty string, so any file it did find would be
  reported corrupt.

The root cause underneath all three is that the artifacts table recorded no
filename. Schema 9 adds ``relative_path`` so validation reads what was written
instead of reconstructing where it should have been.

These tests drive the real validate_job against a temporary data directory.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from movie_review.artifacts import manager as artifacts
from movie_review.artifacts.integrity import IntegrityReport
from movie_review.config.settings import load_settings
from movie_review.domain import Artifact, JobStatus
from movie_review.jobs.manager import JobManager
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.orchestrator import validate_job
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


@dataclass
class _Env:
    data_dir: Path
    db_path: str
    conn: sqlite3.Connection
    job_id: str
    jobs_dir: Path


#: Captured before any monkeypatching, so building the redirected settings does
#: not call back into the patch and recurse.
_REAL_LOAD_SETTINGS = load_settings


def _settings_for(data_dir: Path) -> Any:
    """A settings object whose data_dir is the temporary one.

    validate_job reads the data directory from settings, not from its arguments,
    so a test that does not redirect it will scan the repository's own data dir.
    """
    base = _REAL_LOAD_SETTINGS()
    return base.model_copy(
        update={"paths": base.paths.model_copy(update={"data_dir": str(data_dir)})}
    )


def _redirect(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> None:
    from movie_review.config import settings as settings_module

    monkeypatch.setattr(settings_module, "load_settings", lambda *a, **k: _settings_for(data_dir))


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Env:
    data_dir = tmp_path / "data"
    db_path = str(data_dir / "jobs.db")
    conn = connect(bootstrap(db_path))
    manager = JobManager(conn)
    job = manager.create(str(tmp_path / "movie.mp4"))
    manager.transition(job.job_id, JobStatus.INGESTING)
    manager.transition(job.job_id, JobStatus.MEDIA_READY)

    _redirect(monkeypatch, data_dir)
    return _Env(
        data_dir=data_dir,
        db_path=db_path,
        conn=conn,
        job_id=job.job_id,
        jobs_dir=data_dir / "jobs",
    )


def _write(env: _Env, relative: str, data: bytes) -> Path:
    target = env.jobs_dir / env.job_id / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _record(env: _Env, relative: str, path: Path, artifact_id: str, **kwargs: Any) -> None:
    repo.save_artifact(
        env.conn,
        Artifact(
            artifact_id=artifact_id,
            job_id=env.job_id,
            stage=kwargs.pop("stage", "ingest"),
            relative_path=artifacts.relative_artifact_path(env.jobs_dir, env.job_id, path),
            input_hash=artifacts.sha256_file(path),
            output_hash=artifacts.sha256_file(path),
            **kwargs,
        ),
    )


def _report(env: _Env) -> IntegrityReport:
    return validate_job(env.job_id, env.db_path)


# ---------------------------------------------------------------------------
# The layout that actually exists
# ---------------------------------------------------------------------------


def test_a_recorded_artifact_is_found(env: _Env) -> None:
    """The regression: media.json sits under jobs/, and it must be found.

    The old check looked under <data>/<job_id>/ and reported a perfectly good
    job invalid.
    """
    path = _write(env, "media/media.json", b'{"file": "movie.mp4"}')
    _record(env, "media/media.json", path, f"{env.job_id}-ingest-media")

    report = _report(env)

    assert report.checked == 1
    assert report.ok == 1
    assert report.passed is True


def test_an_artifact_outside_its_stage_directory_is_found(env: _Env) -> None:
    """ingest records stage 'ingest' and writes into media/.

    This is why the stage name cannot be used as the directory: four stages do
    not write where their name says.
    """
    path = _write(env, "media/proxy.mp4", b"proxy-bytes")
    _record(env, "media/proxy.mp4", path, f"{env.job_id}-proxy-video", stage="proxy")

    report = _report(env)

    assert report.passed is True
    assert report.ok == 1


def test_a_file_at_the_job_root_is_found(env: _Env) -> None:
    """movie-analysis.json is written at the job root, not in a stage directory."""
    path = _write(env, "movie-analysis.json", b"{}")
    _record(env, "movie-analysis.json", path, f"{env.job_id}-movie-analysis", stage="story")

    report = _report(env)

    assert report.passed is True


# ---------------------------------------------------------------------------
# Real damage is still detected
# ---------------------------------------------------------------------------


def test_a_deleted_artifact_is_reported_missing(env: _Env) -> None:
    path = _write(env, "scenes/scenes.json", b"[]")
    _record(env, "scenes/scenes.json", path, f"{env.job_id}-scenes", stage="scenes")
    path.unlink()

    report = _report(env)

    assert report.passed is False
    assert report.missing == ["scenes/scenes.json"]


def test_a_modified_artifact_is_reported_corrupt(env: _Env) -> None:
    path = _write(env, "transcript/transcript.json", b'{"segments": []}')
    _record(env, "transcript/transcript.json", path, f"{env.job_id}-transcript", stage="transcript")
    path.write_bytes(b'{"segments": [{"text": "edited by hand"}]}')

    report = _report(env)

    assert report.passed is False
    assert report.corrupt == ["transcript/transcript.json"]


def test_every_recorded_artifact_is_checked(env: _Env) -> None:
    """No guessing: the table decides what exists, not the job status."""
    for relative, stage in (
        ("media/media.json", "ingest"),
        ("scenes/scenes.json", "scenes"),
        ("transcript/transcript.json", "transcript"),
        ("vision/vision.json", "vision"),
        ("review/review-script.json", "review"),
    ):
        path = _write(env, relative, b"{}")
        _record(env, relative, path, f"{env.job_id}-{stage}", stage=stage)

    report = _report(env)

    assert report.checked == 5
    assert report.ok == 5
    assert report.passed is True


def test_only_what_ran_is_required(env: _Env) -> None:
    """A job that only ingested must not be failed for a transcript it never made."""
    path = _write(env, "media/media.json", b"{}")
    _record(env, "media/media.json", path, f"{env.job_id}-ingest-media")

    report = _report(env)

    assert report.missing == []
    assert report.corrupt == []
    assert report.passed is True


# ---------------------------------------------------------------------------
# Records that cannot be located
# ---------------------------------------------------------------------------


def test_a_row_without_a_path_is_reported_not_guessed(env: _Env) -> None:
    """Predates schema 9. Guessing a path is what made this wrong before."""
    repo.save_artifact(
        env.conn,
        Artifact(
            artifact_id=f"{env.job_id}-legacy",
            job_id=env.job_id,
            stage="ingest",
            input_hash="a" * 64,
            output_hash="b" * 64,
        ),
    )

    report = _report(env)

    assert report.unlocated == [f"{env.job_id}-legacy"]
    assert report.checked == 0
    # Missing coverage, not damage: there is nothing wrong with the job.
    assert report.passed is True


def test_a_row_without_a_hash_is_checked_for_existence(env: _Env) -> None:
    """Comparing against a hash that was never recorded would fail every file."""
    path = _write(env, "media/media.json", b"{}")
    repo.save_artifact(
        env.conn,
        Artifact(
            artifact_id=f"{env.job_id}-nohash",
            job_id=env.job_id,
            stage="ingest",
            relative_path=artifacts.relative_artifact_path(env.jobs_dir, env.job_id, path),
            input_hash="a" * 64,
        ),
    )

    report = _report(env)

    assert report.checked == 1
    assert report.ok == 1
    assert report.corrupt == []
    assert report.passed is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_a_job_with_no_artifacts_yet_reports_nothing_missing(env: _Env) -> None:
    """A fresh job is not invalid; it simply has nothing to verify."""
    report = _report(env)

    assert report.checked == 0
    assert report.passed is True


def test_an_unknown_job_is_reported_not_silently_valid(env: _Env) -> None:
    """The old code would have returned True for an id that does not exist."""
    with pytest.raises(JobNotFoundError):
        validate_job("job_does_not_exist", env.db_path)


def test_a_traversal_path_is_refused(env: _Env) -> None:
    """A tampered row must not make the scanner read outside the job."""
    (env.data_dir / "secret.txt").write_bytes(b"TOP SECRET")
    repo.save_artifact(
        env.conn,
        Artifact(
            artifact_id=f"{env.job_id}-evil",
            job_id=env.job_id,
            stage="ingest",
            relative_path="../../secret.txt",
            input_hash="a" * 64,
            output_hash="b" * 64,
        ),
    )

    report = _report(env)

    assert report.unsafe == ["../../secret.txt"]
    assert report.passed is False


# ---------------------------------------------------------------------------
# The CLI surfaces the detail
# ---------------------------------------------------------------------------


def test_cli_prints_what_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A single word cannot tell an operator which file to restore."""
    import importlib

    from typer.testing import CliRunner

    cliapp = importlib.import_module("movie_review.cli.app")

    data_dir = tmp_path / "data"
    db_path = str(data_dir / "jobs.db")
    conn = connect(bootstrap(db_path))
    manager = JobManager(conn)
    job = manager.create(str(tmp_path / "movie.mp4"))
    _redirect(monkeypatch, data_dir)

    path = data_dir / "jobs" / job.job_id / "scenes" / "scenes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"[]")
    repo.save_artifact(
        conn,
        Artifact(
            artifact_id=f"{job.job_id}-scenes",
            job_id=job.job_id,
            stage="scenes",
            relative_path=artifacts.relative_artifact_path(data_dir / "jobs", job.job_id, path),
            input_hash="a" * 64,
            output_hash="b" * 64,
        ),
    )
    path.unlink()

    result = CliRunner().invoke(cliapp.app, ["validate", job.job_id, "--db-path", db_path])

    assert result.exit_code == 1
    assert "valid=False" in result.output
    assert "scenes/scenes.json" in result.output
    assert "missing" in result.output
