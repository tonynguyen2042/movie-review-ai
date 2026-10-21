"""T015 acceptance: adaptive planning and frame extraction."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job
from movie_review.media import ffmpeg as ff
from movie_review.media.frames import (
    FrameSamplingError,
    SamplingConfig,
    SamplingResult,
    extract_frame,
    frame_filename,
    plan_count,
    sample_movie,
    sample_timestamps,
    sampling_config_from,
)
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def test_plan_count_buckets() -> None:
    assert plan_count(5.0) == 3
    assert plan_count(9.99) == 3
    assert plan_count(10.0) == 6
    assert plan_count(59.99) == 6
    assert plan_count(60.0) == 12
    assert plan_count(600.0) == 12
    with pytest.raises(FrameSamplingError):
        plan_count(-1.0)


def test_plan_count_custom_config() -> None:
    config = SamplingConfig(
        short_threshold=5.0,
        medium_threshold=20.0,
        short_frames=2,
        medium_frames=4,
        long_frames=8,
    )
    assert plan_count(4.0, config) == 2
    assert plan_count(10.0, config) == 4
    assert plan_count(30.0, config) == 8
    with pytest.raises(ValueError):
        SamplingConfig(short_threshold=20.0, medium_threshold=10.0)
    with pytest.raises(ValueError):
        SamplingConfig(short_frames=1)


def test_sample_timestamps_evenly_spaced() -> None:
    assert sample_timestamps(0.0, 3.0, 4) == [0.0, 0.75, 1.5, 2.25]
    assert sample_timestamps(10.0, 20.0, 2) == [10.0, 15.0]
    assert all(t < 3.0 for t in sample_timestamps(0.0, 3.0, 4))
    with pytest.raises(FrameSamplingError):
        sample_timestamps(0.0, 1.0, 1)
    with pytest.raises(FrameSamplingError):
        sample_timestamps(2.0, 2.0, 3)


def test_frame_filename_deterministic() -> None:
    assert frame_filename("scene_000001", 1.5) == "scene_000001-00001500.jpg"
    assert frame_filename("scene_000001", 1.5) == frame_filename("scene_000001", 1.5)


def _fake_run(binary: str, args: list[str]) -> str:
    dest = Path(args[-1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"frame-bytes")
    return ""


@dataclass
class Harness:
    conn: sqlite3.Connection
    jobs_dir: Path
    cache: CacheManager
    source: Path

    def sample(self, run_fn: Callable[..., str] | None = None) -> SamplingResult:
        return sample_movie(
            self.source,
            [("scene_000001", 0.0, 5.0), ("scene_000002", 5.0, 35.0)],
            job_id="job_1",
            jobs_dir=self.jobs_dir,
            conn=self.conn,
            cache=self.cache,
            run_fn=_fake_run if run_fn is None else run_fn,
        )


def _harness(tmp_path: Path) -> Harness:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    source = tmp_path / "m.mp4"
    source.write_bytes(b"source-bytes")
    return Harness(
        conn=conn,
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        source=source,
    )


def test_extract_frame_happy_path(tmp_path: Path) -> None:
    dest = extract_frame(tmp_path / "s.mp4", 1.0, tmp_path / "f.jpg", run_fn=_fake_run)
    assert dest.is_file()


def test_extract_frame_failure(tmp_path: Path) -> None:
    def _fail(binary: str, args: list[str]) -> str:
        raise ff.ProcessError(binary, args, "boom")

    with pytest.raises(FrameSamplingError, match="Cannot extract frame"):
        extract_frame(tmp_path / "s.mp4", 1.0, tmp_path / "f.jpg", run_fn=_fail)


def test_extract_frame_missing_output(tmp_path: Path) -> None:
    def _noop(binary: str, args: list[str]) -> str:
        return ""

    with pytest.raises(FrameSamplingError, match="no file"):
        extract_frame(tmp_path / "s.mp4", 1.0, tmp_path / "f.jpg", run_fn=_noop)


def test_sample_movie_writes_frames(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    result = harness.sample()
    assert result.cache_hit is False
    assert len(result.frames) == 3 + 6
    assert all(frame.path.is_file() for frame in result.frames)
    assert result.manifest_path.is_file()
    assert repo.get_artifact(harness.conn, "job_1-frames") is not None


def test_sample_movie_second_run_hits_cache(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    first = harness.sample()

    def _boom(binary: str, args: list[str]) -> str:
        raise AssertionError("ffmpeg must not run on cache hit")

    second = harness.sample(run_fn=_boom)
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert [f.timestamp for f in first.frames] == [f.timestamp for f in second.frames]


def test_sample_movie_tampered_frame_regenerates(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    first = harness.sample()
    first.frames[0].path.write_bytes(b"tampered")
    calls: list[int] = []

    def _counting(binary: str, args: list[str]) -> str:
        calls.append(1)
        return _fake_run(binary, args)

    second = harness.sample(run_fn=_counting)
    assert second.cache_hit is False
    assert calls


def test_sample_movie_missing_source(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.source.unlink()
    with pytest.raises(FrameSamplingError, match="not found"):
        harness.sample()


def test_sampling_config_from_settings() -> None:
    config = sampling_config_from(load_settings().pipeline.visual_sampling)
    assert (config.short_frames, config.medium_frames, config.long_frames) == (3, 6, 12)
    assert plan_count(5.0, config) == 3


@pytest.mark.ffmpeg
def test_sample_movie_real_end_to_end(tmp_path: Path) -> None:
    source = tmp_path / "t.mp4"
    ff.check(
        "ffmpeg",
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=25:duration=2",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-an",
            str(source),
        ],
    )
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    result = sample_movie(
        source,
        [("scene_000001", 0.0, 2.0)],
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        cache=CacheManager(tmp_path / "cache"),
    )
    assert len(result.frames) == 3
    assert all(frame.path.is_file() for frame in result.frames)
    conn.close()
