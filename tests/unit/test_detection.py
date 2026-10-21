"""T014 acceptance: scene detection stage maps cuts to stable scenes."""

import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus
from movie_review.jobs.manager import JobManager
from movie_review.media import ffmpeg as ff
from movie_review.media.detection import (
    ScenesResult,
    SceneStageError,
    detect_scenes_stage,
    resolve_analysis_file,
)
from movie_review.media.scenes import DetectionResult, SceneCut, SceneDetectionError
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect

NEEDS_FFMPEG = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe binaries not installed",
)


@dataclass
class Harness:
    conn: sqlite3.Connection
    ctx: StageContext
    source: Path

    def stage(
        self,
        detect_fn: Callable[..., DetectionResult] | None = None,
        prefer_proxy: bool = False,
    ) -> ScenesResult:
        return detect_scenes_stage(
            self.source,
            self.ctx,
            prefer_proxy=prefer_proxy,
            detect_fn=detect_fn or _fake_detect,
        )


def _fake_detect(path: str | Path, **kwargs: object) -> DetectionResult:
    del path, kwargs
    return DetectionResult(
        cuts=[SceneCut(start=0.0, end=1.0), SceneCut(start=1.0, end=2.5)], fps=25.0
    )


def _harness(tmp_path: Path) -> Harness:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    manager.transition("job_1", JobStatus.INGESTING)
    manager.transition("job_1", JobStatus.MEDIA_READY)
    source = tmp_path / "m.mp4"
    source.write_bytes(b"source-bytes")
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )
    return Harness(conn=conn, ctx=ctx, source=source)


def test_stage_happy_path(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    result = harness.stage()
    assert [s.scene_id for s in result.scenes] == ["scene_000001", "scene_000002"]
    assert result.scenes[1].duration == pytest.approx(1.5)
    assert result.cache_hit is False
    assert result.scenes_path.is_file()
    assert harness.ctx.manager.get("job_1").status is JobStatus.SCENES_READY
    assert [s.scene_id for s in repo.list_scenes(harness.conn, "job_1")] == [
        "scene_000001",
        "scene_000002",
    ]
    assert repo.get_artifact(harness.conn, "job_1-scenes") is not None


def test_stage_second_run_hits_cache(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.stage()

    def _boom(path: str | Path, **kwargs: object) -> DetectionResult:
        raise AssertionError("detector must not run on cache hit")

    result = harness.stage(detect_fn=_boom)
    assert result.cache_hit is True


def test_stage_uses_the_source_by_default(tmp_path: Path) -> None:
    """The analysed file must not depend on how far a previous run got.

    The proxy is built in the vision stage, which runs after this one. So
    preferring it made the first run detect on the source and any later run
    detect on the proxy -- different cuts for the same movie, and a cache
    miss every time.
    """
    harness = _harness(tmp_path)
    proxy = tmp_path / "jobs" / "job_1" / "media" / "proxy.mp4"
    proxy.parent.mkdir(parents=True, exist_ok=True)
    proxy.write_bytes(b"proxy-bytes")
    result = harness.stage()
    assert result.analyzed_file == harness.source
    assert (
        resolve_analysis_file(
            harness.source,
            jobs_dir=tmp_path / "jobs",
            job_id="job_1",
            prefer_proxy=False,
        )
        == harness.source
    )


def test_stage_uses_the_proxy_when_it_is_asked_for(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    proxy = tmp_path / "jobs" / "job_1" / "media" / "proxy.mp4"
    proxy.parent.mkdir(parents=True, exist_ok=True)
    proxy.write_bytes(b"proxy-bytes")
    result = harness.stage(prefer_proxy=True)
    assert result.analyzed_file == proxy


def test_stage_unknown_job(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.ctx.job_id = "job_2"
    with pytest.raises(SceneStageError, match="Unknown job"):
        harness.stage()


def test_stage_failed_job_rejected(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.ctx.manager.fail("job_1", "ingest", "earlier")
    with pytest.raises(SceneStageError, match="failed"):
        harness.stage()


def test_stage_detection_failure_fails_job(tmp_path: Path) -> None:
    harness = _harness(tmp_path)

    def _bad(path: str | Path, **kwargs: object) -> DetectionResult:
        raise SceneDetectionError("nope")

    with pytest.raises(SceneStageError, match="Cannot detect scenes"):
        harness.stage(detect_fn=_bad)
    job = harness.ctx.manager.get("job_1")
    assert job.status is JobStatus.FAILED
    assert job.failed_stage == "scenes"


def test_stage_rerun_past_scenes_ready(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.stage()
    harness.ctx.manager.transition("job_1", JobStatus.TRANSCRIPT_READY)
    result = harness.stage()
    assert result.cache_hit is True
    assert harness.ctx.manager.get("job_1").status is JobStatus.TRANSCRIPT_READY


@NEEDS_FFMPEG
def test_stage_real_end_to_end(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    for name, pattern in (("a.mp4", "testsrc"), ("b.mp4", "smptebars")):
        ff.check(
            "ffmpeg",
            [
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"{pattern}=size=320x240:rate=25:duration=1",
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "libx264",
                "-an",
                str(tmp_path / name),
            ],
        )
    listing = tmp_path / "parts.txt"
    listing.write_text(
        f"file '{tmp_path / 'a.mp4'}'\nfile '{tmp_path / 'b.mp4'}'\n", encoding="utf-8"
    )
    source = tmp_path / "cut.mp4"
    ff.check(
        "ffmpeg",
        ["-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(source)],
    )
    harness.source = source
    result = detect_scenes_stage(source, harness.ctx, prefer_proxy=False)
    assert [s.scene_id for s in result.scenes] == ["scene_000001", "scene_000002"]
    assert harness.ctx.manager.get("job_1").status is JobStatus.SCENES_READY
