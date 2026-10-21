"""T011 acceptance: ingest follows the stage contract end to end."""

import json
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus, MovieMetadata
from movie_review.jobs.manager import JobManager
from movie_review.media import ffmpeg as ff
from movie_review.media.ingest import IngestError, ingest_movie
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from tests.helpers import (
    _fake_probe,
)


def _context(tmp_path: Path, job_id: str = "job_1") -> StageContext:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id=job_id, input_file="m.mp4"))
    return StageContext(
        job_id=job_id,
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=JobManager(conn),
        settings=load_settings(),
        conn=conn,
    )


def test_ingest_happy_path(tmp_path: Path) -> None:
    source = tmp_path / "m.mp4"
    source.write_bytes(b"fake-movie")
    ctx = _context(tmp_path)
    result = ingest_movie(source, ctx, probe_fn=_fake_probe)
    assert result.cache_hit is False
    assert result.media_path.is_file()
    assert result.movie.id == "movie-job_1"
    assert ctx.manager.get("job_1").status is JobStatus.MEDIA_READY
    assert repo.get_movie(ctx.conn, "job_1") == result.movie
    assert repo.get_artifact(ctx.conn, "job_1-ingest-media") is not None


def test_ingest_second_run_hits_cache(tmp_path: Path) -> None:
    source = tmp_path / "m.mp4"
    source.write_bytes(b"fake-movie")
    ctx = _context(tmp_path)
    ingest_movie(source, ctx, probe_fn=_fake_probe)
    result = ingest_movie(source, ctx, probe_fn=_fake_probe)
    assert result.cache_hit is True
    assert ctx.manager.get("job_1").status is JobStatus.MEDIA_READY


def test_ingest_missing_file(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    with pytest.raises(IngestError, match="not found"):
        ingest_movie(tmp_path / "absent.mp4", ctx, probe_fn=_fake_probe)
    assert ctx.manager.get("job_1").status is JobStatus.CREATED


def test_ingest_unknown_job(tmp_path: Path) -> None:
    ctx = _context(tmp_path, job_id="job_1")
    ctx.job_id = "job_2"
    with pytest.raises(IngestError, match="Unknown job"):
        ingest_movie(tmp_path / "m.mp4", ctx, probe_fn=_fake_probe)


def test_ingest_failed_job_rejected(tmp_path: Path) -> None:
    source = tmp_path / "m.mp4"
    source.write_bytes(b"x")
    ctx = _context(tmp_path)
    ctx.manager.transition("job_1", JobStatus.INGESTING)
    ctx.manager.fail("job_1", "ingest", "earlier")
    with pytest.raises(IngestError, match="failed"):
        ingest_movie(source, ctx, probe_fn=_fake_probe)


def test_ingest_probe_failure_fails_job(tmp_path: Path) -> None:
    source = tmp_path / "m.mp4"
    source.write_bytes(b"x")

    def _bad_probe(path: str) -> MovieMetadata:
        raise ff.ProbeError(path, "no video stream")

    ctx = _context(tmp_path)
    with pytest.raises(IngestError, match="Cannot ingest"):
        ingest_movie(source, ctx, probe_fn=_bad_probe)
    job = ctx.manager.get("job_1")
    assert job.status is JobStatus.FAILED
    assert job.failed_stage == "ingest"


def test_ingest_rerun_past_media_ready(tmp_path: Path) -> None:
    source = tmp_path / "m.mp4"
    source.write_bytes(b"x")
    ctx = _context(tmp_path)
    ingest_movie(source, ctx, probe_fn=_fake_probe)
    ctx.manager.transition("job_1", JobStatus.SCENES_READY)
    result = ingest_movie(source, ctx, probe_fn=_fake_probe)
    assert result.cache_hit is True
    assert ctx.manager.get("job_1").status is JobStatus.SCENES_READY


def test_context_from_settings(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    ctx = StageContext.from_settings(load_settings(), conn, "job_9")
    assert ctx.jobs_dir == Path("data") / "jobs"
    assert ctx.job_id == "job_9"
    conn.close()


@pytest.mark.ffmpeg
def test_ingest_real_fixture(tmp_path: Path) -> None:
    target = tmp_path / "t.mp4"
    ff.check(
        "ffmpeg",
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=25:duration=1",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-an",
            str(target),
        ],
    )
    ctx = _context(tmp_path)
    result = ingest_movie(target, ctx)
    assert (result.movie.metadata.width, result.movie.metadata.height) == (320, 240)
    assert ctx.manager.get("job_1").status is JobStatus.MEDIA_READY


def test_media_json_structure(tmp_path: Path) -> None:
    source = tmp_path / "m.mp4"
    source.write_bytes(b"x")
    ctx = _context(tmp_path)
    result = ingest_movie(source, ctx, probe_fn=_fake_probe)
    document = json.loads(result.media_path.read_text(encoding="utf-8"))
    assert document["job_id"] == "job_1"
    assert document["stage"] == "ingest"
    assert document["movie"]["metadata"]["width"] == 640
