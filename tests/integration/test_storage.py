"""T005 acceptance: schema bootstrap, migrations, repository round-trips."""

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from movie_review.domain import (
    Artifact,
    Claim,
    ClaimStatus,
    ClaimType,
    Evidence,
    EvidenceType,
    Job,
    JobStatus,
    Movie,
    MovieMetadata,
    Scene,
)
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect, get_schema_version, migrate
from movie_review.storage.schema import SCHEMA_VERSION


@pytest.fixture()
def db(tmp_path: Path) -> Generator[sqlite3.Connection]:
    path = bootstrap(tmp_path / "jobs" / "test.db")
    assert path.is_file()
    conn = connect(path)
    yield conn
    conn.close()


@pytest.fixture()
def job(db: sqlite3.Connection) -> Job:
    job = Job(job_id="job_1", input_file="movie.mp4")
    repo.save_job(db, job)
    return job


def test_bootstrap_records_schema_version(tmp_path: Path) -> None:
    path = bootstrap(tmp_path / "a.db")
    with connect(path) as conn:
        assert get_schema_version(conn) == SCHEMA_VERSION
    # Idempotent: re-running changes nothing and loses nothing.
    bootstrap(path)
    with connect(path) as conn:
        assert get_schema_version(conn) == SCHEMA_VERSION


def test_migrate_rejects_newer_database(tmp_path: Path) -> None:
    path = tmp_path / "new.db"
    with connect(path) as conn:
        conn.execute("PRAGMA user_version = 99")
    with connect(path) as conn, pytest.raises(ValueError, match="newer than supported"):
        migrate(conn)


def test_job_round_trip(db: sqlite3.Connection, job: Job) -> None:
    assert repo.get_job(db, "job_1") == job
    assert repo.get_job(db, "missing") is None


def test_movie_round_trip(db: sqlite3.Connection, job: Job) -> None:
    movie = Movie(
        id="m1",
        metadata=MovieMetadata(
            file="movie.mp4",
            sha256="b" * 64,
            duration_seconds=100.0,
            width=1280,
            height=720,
            fps=30.0,
            video_codec="h264",
        ),
    )
    repo.save_movie(db, job.job_id, movie)
    assert repo.get_movie(db, job.job_id) == movie
    assert repo.get_movie(db, "missing") is None


def test_scene_list_ordered_and_replaceable(db: sqlite3.Connection, job: Job) -> None:
    repo.save_scene(db, job.job_id, Scene(scene_id="s2", start=10.0, end=15.0, duration=5.0))
    repo.save_scene(db, job.job_id, Scene(scene_id="s1", start=0.0, end=10.0, duration=10.0))
    scenes = repo.list_scenes(db, job.job_id)
    assert [s.scene_id for s in scenes] == ["s1", "s2"]
    repo.save_scene(db, job.job_id, Scene(scene_id="s1", start=0.0, end=10.0, duration=10.0))
    assert len(repo.list_scenes(db, job.job_id)) == 2
    assert repo.get_scene(db, job.job_id, "s2") is not None
    assert repo.get_scene(db, job.job_id, "missing") is None


def test_resaving_job_preserves_children(db: sqlite3.Connection, job: Job) -> None:
    """Re-saving a job (e.g. a lifecycle transition) must not cascade-wipe rows."""
    repo.save_scene(db, job.job_id, Scene(scene_id="s", start=0.0, end=1.0, duration=1.0))
    updated = job.model_copy(update={"status": JobStatus.INGESTING})
    repo.save_job(db, updated)
    assert repo.get_job(db, job.job_id) == updated
    assert repo.get_scene(db, job.job_id, "s") is not None


def test_foreign_keys_enforced(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_scene(db, "no-such-job", Scene(scene_id="s", start=0.0, end=1.0, duration=1.0))


def test_cascade_delete_removes_children(db: sqlite3.Connection, job: Job) -> None:
    repo.save_scene(db, job.job_id, Scene(scene_id="s", start=0.0, end=1.0, duration=1.0))
    with db:
        db.execute("DELETE FROM jobs WHERE job_id = ?", (job.job_id,))
    assert repo.list_scenes(db, job.job_id) == []
    assert repo.get_job(db, job.job_id) is None


def test_evidence_filter_by_type(db: sqlite3.Connection, job: Job) -> None:
    repo.save_evidence(
        db, job.job_id, Evidence(id="e1", type=EvidenceType.DIALOGUE, source_id="seg_1")
    )
    repo.save_evidence(db, job.job_id, Evidence(id="e2", type=EvidenceType.VISUAL, source_id="f_1"))
    assert len(repo.list_evidence(db, job.job_id)) == 2
    (dialogue,) = repo.list_evidence(db, job.job_id, EvidenceType.DIALOGUE)
    assert dialogue.id == "e1"


def test_claim_round_trip(db: sqlite3.Connection, job: Job) -> None:
    claim = Claim(
        claim_id="c1",
        text="Sarah knew.",
        type=ClaimType.PLOT_FACT,
        evidence=["event_1"],
        status=ClaimStatus.SUPPORTED,
    )
    repo.save_claim(db, job.job_id, claim)
    assert repo.get_claim(db, job.job_id, "c1") == claim
    assert [c.claim_id for c in repo.list_claims(db, job.job_id)] == ["c1"]


def test_artifact_stage_filter(db: sqlite3.Connection, job: Job) -> None:
    repo.save_artifact(
        db, Artifact(artifact_id="a1", job_id=job.job_id, stage="ingest", input_hash="h1")
    )
    repo.save_artifact(
        db, Artifact(artifact_id="a2", job_id=job.job_id, stage="ingest", input_hash="h2")
    )
    assert repo.get_artifact(db, "a1") is not None
    assert repo.get_artifact(db, "missing") is None
    assert len(repo.list_artifacts(db, job.job_id)) == 2
    assert len(repo.list_artifacts(db, job.job_id, stage="ingest")) == 2
    assert repo.list_artifacts(db, job.job_id, stage="scenes") == []
