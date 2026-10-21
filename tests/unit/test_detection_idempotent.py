"""Scene detection has to give the same answer every time.

T129 regression. Two things made the stage non-idempotent.

First, the analysed file was resolved with a preference for the proxy, and
the proxy is built in the vision stage -- which runs *after* the scenes
stage. So the first run detected on the source and any later run detected on
the proxy. The analysed file is part of the cache key, so the second run
missed the cache and produced a different set of cuts for the same movie.

Second, the new scenes were written over the old ones without clearing the
set first, so any scene the new detection did not contain survived with its
old boundaries. A re-run left a mix of two timelines, and the timeline
consistency metric compared events against that mixture.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus
from movie_review.jobs.manager import JobManager
from movie_review.media.detection import detect_scenes_stage, resolve_analysis_file
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _ctx__detection_idempotent(tmp_path: Path) -> tuple[StageContext, sqlite3.Connection]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    manager.transition("job_1", JobStatus.INGESTING)
    manager.transition("job_1", JobStatus.MEDIA_READY)
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
    )
    return ctx, conn


def _cuts(*spans: tuple[float, float]):
    from movie_review.media.scenes import DetectionResult, SceneCut

    return DetectionResult(cuts=[SceneCut(start=start, end=end) for start, end in spans], fps=30.0)


def test_the_source_is_used_when_no_proxy_is_asked_for(tmp_path: Path) -> None:
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"\x00")
    proxy = tmp_path / "jobs" / "job_1" / "media" / "proxy.mp4"
    proxy.parent.mkdir(parents=True)
    proxy.write_bytes(b"\x00")

    resolved = resolve_analysis_file(source, jobs_dir=tmp_path / "jobs", job_id="job_1")
    assert resolved == source


def test_the_proxy_is_used_when_it_is_asked_for(tmp_path: Path) -> None:
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"\x00")
    proxy = tmp_path / "jobs" / "job_1" / "media" / "proxy.mp4"
    proxy.parent.mkdir(parents=True)
    proxy.write_bytes(b"\x00")

    resolved = resolve_analysis_file(
        source, jobs_dir=tmp_path / "jobs", job_id="job_1", prefer_proxy=True
    )
    assert resolved == proxy


def test_a_rerun_produces_the_same_scenes(tmp_path: Path) -> None:
    """The same movie must give the same cuts, run after run."""
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"\x00")
    ctx, conn = _ctx__detection_idempotent(tmp_path)
    try:
        first = detect_scenes_stage(
            source, ctx, detect_fn=lambda *a, **k: _cuts((0.0, 10.0), (10.0, 25.0))
        )
        second = detect_scenes_stage(
            source, ctx, detect_fn=lambda *a, **k: _cuts((0.0, 10.0), (10.0, 25.0))
        )
        assert [s.scene_id for s in first.scenes] == [s.scene_id for s in second.scenes]
        assert [(s.start, s.end) for s in first.scenes] == [(s.start, s.end) for s in second.scenes]
    finally:
        conn.close()


def test_a_rerun_does_not_leave_stale_scenes(tmp_path: Path) -> None:
    """A scene the new detection does not contain must not survive."""
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"\x00")
    ctx, conn = _ctx__detection_idempotent(tmp_path)
    try:
        detect_scenes_stage(source, ctx, detect_fn=lambda *a, **k: _cuts((0.0, 10.0), (10.0, 25.0)))
        assert len(repo.list_scenes(conn, "job_1")) == 2

        # A different movie content, so the cache key changes and the
        # detection really runs again with a different result.
        source.write_bytes(b"\x00\x01")
        detect_scenes_stage(
            source,
            ctx,
            detect_fn=lambda *a, **k: _cuts(
                (0.0, 8.0),
            ),
        )
        stored = repo.list_scenes(conn, "job_1")
        assert len(stored) == 1, f"a stale scene survived: {[s.scene_id for s in stored]}"
        assert stored[0].end == 8.0
    finally:
        conn.close()
