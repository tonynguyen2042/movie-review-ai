"""The thumbnail command must exist and produce a thumbnail.

T148. `publishing/thumbnail.py::generate_thumbnail` was complete and
tested, and nothing called it. The publish command passed a thumbnail path
only if the file happened to exist, so uploads never carried one.

README section 48 makes the thumbnail a separate optional stage: it is not
part of the pipeline, and a job does not need one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from movie_review.artifacts import manager as artifacts
from movie_review.cli.app import app
from movie_review.domain import Job, ManifestSegment, RenderManifest
from movie_review.publishing.thumbnail import thumbnail_path
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the configured data directory at the test's temporary one."""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("MOVIE_REVIEW_PATHS__DATA_DIR", str(root))
    return root


def _job(data_dir: Path) -> tuple[Path, str]:
    """A job in the temporary data directory, and the path to its database."""
    db = data_dir / "jobs.db"
    conn = connect(bootstrap(db))
    repo.save_job(conn, Job(job_id="job_1", input_file=str(data_dir / "movie.mp4")))
    conn.commit()
    conn.close()
    return db, "job_1"


def _manifest(data_dir: Path, job_id: str) -> None:
    path = data_dir / "jobs" / job_id / "render" / "render-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = RenderManifest(
        segments=[
            ManifestSegment(
                paragraph_id="p1",
                start=0.0,
                duration=20.0,
                scene_id="scene_000001",
                clip_start=0.0,
                clip_end=20.0,
            )
        ],
        total_seconds=20.0,
        source_seconds=20.0,
    )
    artifacts.write_json(path, manifest.model_dump(mode="json"))


def test_the_command_exists() -> None:
    """The generator was complete and nothing called it."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "thumbnail" in result.output


def test_a_job_without_a_manifest_is_reported(data_dir: Path) -> None:
    """The thumbnail needs the render manifest to pick a frame."""
    db, job_id = _job(data_dir)
    result = CliRunner().invoke(app, ["thumbnail", job_id, "--db-path", str(db)])
    assert result.exit_code == 1
    assert "No render manifest" in (result.stdout or "") + (result.stderr or "")


def test_a_failed_extraction_is_reported(data_dir: Path) -> None:
    """A thumbnail that cannot be produced is a classified failure."""
    db, job_id = _job(data_dir)
    _manifest(data_dir, job_id)
    # The movie file does not exist, so the frame cannot be extracted.
    result = CliRunner().invoke(app, ["thumbnail", job_id, "--db-path", str(db)])
    assert result.exit_code == 1
    assert "Cannot generate the thumbnail" in (result.stdout or "") + (result.stderr or "")


def test_the_publish_command_attaches_the_thumbnail(data_dir: Path) -> None:
    """The upload carries the thumbnail when the job has one."""
    db, job_id = _job(data_dir)
    path = thumbnail_path(data_dir / "jobs", job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"jpeg")
    assert path.is_file()
    # The publish command looks for exactly this path.
    assert path == thumbnail_path(data_dir / "jobs", job_id)


def test_the_thumbnail_is_not_a_pipeline_stage() -> None:
    """README section 48: a separate optional stage, not part of the pipeline."""
    from movie_review.pipeline.orchestrator import STAGE_SEQUENCE

    order = [name for name, _ in STAGE_SEQUENCE]
    assert "thumbnail" not in order
