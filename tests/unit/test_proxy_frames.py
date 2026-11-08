"""Frames must come from the analysis proxy, not the source (T104).

The vision adapter inlines every frame as a base64 data URI, so a 4K Blu-ray
JPEG is megabytes per frame and a feature film would put gigabytes on the wire
to the VLM. Frames are now read from a downscaled proxy, which is what the
frame-sampling docstring always said should happen.

The dangerous part is not the size, it is the cache. Frames sampled from the
source and from the proxy share scenes, timestamps and bucket settings -- only
the pixels differ. If the cache key still named the source, switching to the
proxy would silently reuse the old full-resolution frames forever.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import movie_review.media.frames as frames_module
import movie_review.media.proxy as media_proxy
from movie_review.artifacts import manager as artifacts
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus, MovieMetadata, Scene
from movie_review.jobs.manager import JobManager
from movie_review.media.frames import SamplingResult
from movie_review.media.proxy import ProxyResult, generate_proxy
from movie_review.pipeline.orchestrator import PipelineContext, _get_stage_function, run_stage
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect

SPANS = [("scene_000001", 0.0, 5.0), ("scene_000002", 10.0, 40.0)]


def _fake_run__proxy_frames(binary: str, args: list[str]) -> str:
    """Stand in for ffmpeg: write a marker at whatever path was requested."""
    dest = Path(args[-1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"jpeg")
    return ""


def _fake_probe__proxy_frames(binary: str) -> MovieMetadata:
    return MovieMetadata(
        file="proxy.mp4",
        sha256="a" * 64,
        duration_seconds=120.0,
        width=1280,
        height=720,
        fps=30.0,
        video_codec="h264",
        audio_codec="aac",
        container="mp4",
    )


@dataclass(frozen=True)
class _Workspace:
    """Typed collaborators; a dict here would need ignores on every access."""

    conn: sqlite3.Connection
    source: Path
    jobs_dir: Path
    cache: CacheManager


@pytest.fixture
def workspace(tmp_path: Path) -> _Workspace:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    source = tmp_path / "m.mp4"
    source.write_bytes(b"source-bytes")
    repo.save_job(conn, Job(job_id="job_p", input_file="m.mp4"))
    return _Workspace(
        conn=conn,
        source=source,
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
    )


def _proxy(workspace: _Workspace) -> ProxyResult:
    return generate_proxy(
        workspace.source,
        job_id="job_p",
        jobs_dir=workspace.jobs_dir,
        conn=workspace.conn,
        cache=workspace.cache,
        max_width=1280,
        max_height=720,
        run_fn=_fake_run__proxy_frames,
        probe_fn=_fake_probe__proxy_frames,
    )


def _sample_from(workspace: _Workspace, media: Path) -> SamplingResult:
    return frames_module.sample_movie(
        media,
        SPANS,
        job_id="job_p",
        jobs_dir=workspace.jobs_dir,
        conn=workspace.conn,
        cache=workspace.cache,
        run_fn=_fake_run__proxy_frames,
    )


# ---------------------------------------------------------------------------
# The proxy itself
# ---------------------------------------------------------------------------


def test_proxy_is_built_at_the_configured_size(workspace: _Workspace) -> None:
    result = _proxy(workspace)

    assert result.path.is_file()
    assert result.width == 1280
    assert result.height == 720
    assert result.cache_hit is False


def test_proxy_is_reused_on_a_second_call(workspace: _Workspace) -> None:
    first = _proxy(workspace)

    def _boom(binary: str, args: list[str]) -> str:
        raise AssertionError("ffmpeg must not run again")

    second = generate_proxy(
        workspace.source,
        job_id="job_p",
        jobs_dir=workspace.jobs_dir,
        conn=workspace.conn,
        cache=workspace.cache,
        max_width=1280,
        max_height=720,
        run_fn=_boom,
        probe_fn=_fake_probe__proxy_frames,
    )

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.path == first.path


# ---------------------------------------------------------------------------
# The cache must distinguish the two media sources
# ---------------------------------------------------------------------------


def test_frames_from_source_and_from_proxy_are_not_interchangeable(
    workspace: _Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Identical scenes and timestamps, different pixels, so nothing may be adopted."""
    proxy = _proxy(workspace)

    from_source = _sample_from(workspace, workspace.source)

    extracted: list[Path] = []

    def _spy_extract(
        src: str | Path,
        ts: float,
        dest: str | Path,
        ffmpeg: str = "ffmpeg",
        _ignored: object = None,
    ) -> Path:
        extracted.append(Path(src))
        result: Path = _REAL_EXTRACT(src, ts, dest, ffmpeg, _fake_run__proxy_frames)
        return result

    monkeypatch.setattr("movie_review.media.frames.extract_frame", _spy_extract)

    from_proxy = _sample_from(workspace, proxy.path)

    assert [f.timestamp for f in from_source.frames] == [f.timestamp for f in from_proxy.frames]
    # Every frame was read from the proxy rather than adopted from the entry
    # the source run left behind -- that entry is a different cache key.
    assert extracted, "nothing was extracted for the proxy run"
    assert set(extracted) == {proxy.path}
    assert from_proxy.cache_hit is False


def test_proxy_frame_run_is_a_cache_hit_the_second_time(workspace: _Workspace) -> None:
    proxy = _proxy(workspace)
    _sample_from(workspace, proxy.path)

    def _boom(binary: str, args: list[str]) -> str:
        raise AssertionError("ffmpeg must not run on a cache hit")

    result = frames_module.sample_movie(
        proxy.path,
        SPANS,
        job_id="job_p",
        jobs_dir=workspace.jobs_dir,
        conn=workspace.conn,
        cache=workspace.cache,
        run_fn=_boom,
    )

    assert result.cache_hit is True


def test_frames_stage_version_records_the_change(workspace: _Workspace) -> None:
    """v1 entries describe source pixels; reusing them would be wrong.

    v3 (T179) means the frames came from one decode pass per scene, which can
    land a frame either side of the v2 millisecond seek, so v2 entries are not
    adopted.
    """
    assert frames_module.STAGE_VERSION == "v3"
    key_source = frames_module.frames_cache_key(
        artifacts.sha256_file(workspace.source), SPANS, frames_module.SamplingConfig()
    )
    key_proxy = frames_module.frames_cache_key(
        artifacts.sha256_file(_proxy(workspace).path), SPANS, frames_module.SamplingConfig()
    )
    assert key_source != key_proxy


# ---------------------------------------------------------------------------
# The stage wires them together
# ---------------------------------------------------------------------------


def _vision_ctx__proxy_frames(workspace: _Workspace) -> PipelineContext:
    manager = JobManager(workspace.conn)
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
    ):
        manager.transition("job_p", state)
    for scene_id, start, end in SPANS:
        repo.save_scene(
            workspace.conn,
            "job_p",
            Scene(scene_id=scene_id, start=start, end=end, duration=end - start),
        )
    return PipelineContext(
        job_id="job_p",
        movie_path=workspace.source,
        jobs_dir=workspace.jobs_dir,
        conn=workspace.conn,
        manager=manager,
        cache=workspace.cache,
        settings=load_settings(),
    )


def test_stage_samples_from_the_proxy_not_the_source(
    workspace: _Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring, asserted on what sample_movie was handed."""
    sampled_paths: list[Path] = []
    real_sample = frames_module.sample_movie

    def _spy(
        media: str | Path, scenes: list[tuple[str, float, float]], **kwargs: Any
    ) -> SamplingResult:
        sampled_paths.append(Path(media))
        return real_sample(media, scenes, **kwargs)

    monkeypatch.setattr("movie_review.media.frames.extract_frame", _forced_extract)
    monkeypatch.setattr(
        "movie_review.vision.analysis.run_visual_analysis", lambda *a, **kw: object()
    )
    # generate_proxy binds run_fn=ff.check as a default argument at definition
    # time, so patching ff.check cannot redirect it. Wrapping the function is
    # the only seam, and the stage resolves the name from this module at call
    # time, so patching the attribute is enough.
    real_generate = media_proxy.generate_proxy

    def _stub_generate(source: str | Path, **kwargs: Any) -> ProxyResult:
        kwargs.setdefault("run_fn", _fake_run__proxy_frames)
        kwargs.setdefault("probe_fn", _fake_probe__proxy_frames)
        return real_generate(source, **kwargs)

    monkeypatch.setattr("movie_review.media.proxy.generate_proxy", _stub_generate)
    # The stage imports sample_movie inside its body, so the module attribute is
    # what the lookup resolves against at call time.
    monkeypatch.setattr("movie_review.media.frames.sample_movie", _spy)

    result = run_stage("vision", _stage__proxy_frames(), _vision_ctx__proxy_frames(workspace))

    assert result.success is True, result.error
    assert len(sampled_paths) == 1
    proxy_path = workspace.jobs_dir / "job_p" / "media" / "proxy.mp4"
    assert sampled_paths[0] == proxy_path, f"sampled from {sampled_paths[0]}"
    assert sampled_paths[0] != workspace.source, "sampled from the source, not the proxy"


def _stage__proxy_frames() -> Callable[[PipelineContext], object]:
    stage = _get_stage_function("vision")
    assert stage is not None
    return stage


def _forced_extract(
    source: str | Path,
    timestamp: float,
    dest: str | Path,
    ffmpeg: str = "ffmpeg",
    _ignored: object = None,
) -> Path:
    result: Path = _REAL_EXTRACT(source, timestamp, dest, ffmpeg, _fake_run__proxy_frames)
    return result


_REAL_EXTRACT = frames_module.extract_frame
