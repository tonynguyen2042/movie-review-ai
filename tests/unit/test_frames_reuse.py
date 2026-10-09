"""Sampling must survive a failed vision run and a fresh job (T102).

Sampling completes before the VLM is ever called, so a stage that fails on a
remote 500 has already paid for every frame. The cache key deliberately excludes
job_id -- frames depend on the movie's hash and the scene spans, not on which
job asked -- but the verification used to require the frames to already sit in
*this* job's directory. So a second ``process`` run over the same movie, which
mints a new job_id, found the cache entry and rejected it, re-decoding every
scene for nothing.

Frames are now adopted per scene, copied across job directories and verified by
sha256 before and after the copy. A scene is adopted whole or not at all: mixing
frames from two passes inside one scene would be visually incoherent.

The manifest is also written after every scene rather than once at the end, so a
sampling run cut short keeps what it finished.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

import movie_review.media.frames as frames_module
from movie_review.artifacts import manager as artifacts
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus, Scene
from movie_review.jobs.manager import JobManager
from movie_review.media.frames import SamplingResult, sample_movie
from movie_review.pipeline.orchestrator import PipelineContext, _get_stage_function, run_stage
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect

SPANS = [("scene_000001", 0.0, 5.0), ("scene_000002", 10.0, 40.0)]


def _vision_stage() -> Callable[[PipelineContext], object]:
    """The vision stage, asserting it exists rather than passing None onwards."""
    stage = _get_stage_function("vision")
    assert stage is not None, "vision stage is missing from the orchestrator"
    return stage


#: Captured before patching. sample_movie passes its own run_fn as the fifth
#: positional argument, so a wrapper that merely defaulted to the stub would
#: forward the real ffmpeg; calling the patched name would recurse forever.
_REAL_EXTRACT = frames_module.extract_frame


@dataclass
class _Workspace:
    """Real collaborators over a temp dir; typed so mypy needs no ignores."""

    conn: sqlite3.Connection
    source: Path
    jobs_dir: Path
    cache: CacheManager
    tmp: Path


@pytest.fixture
def workspace(tmp_path: Path) -> _Workspace:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    source = tmp_path / "m.mp4"
    source.write_bytes(b"source-bytes")
    return _Workspace(
        conn=conn,
        source=source,
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        tmp=tmp_path,
    )


def _fake_run(binary: str, args: list[str]) -> str:
    dest = Path(args[-1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(f"frame-for-{dest.name}".encode())
    return ""


@pytest.fixture
def counter(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Count real extractions; the stub is the only thing that writes frames."""
    calls = {"n": 0}

    def _extract(
        source: str | Path,
        timestamp: float,
        dest: str | Path,
        ffmpeg: str = "ffmpeg",
        _ignored: object = None,
    ) -> Path:
        calls["n"] += 1
        result: Path = _REAL_EXTRACT(source, timestamp, dest, ffmpeg, _fake_run)
        return result

    monkeypatch.setattr(frames_module, "extract_frame", _extract)
    return calls


def _sample(workspace: _Workspace, job_id: str) -> SamplingResult:
    # artifacts has a foreign key onto jobs, so every job we sample for must
    # exist first. save_job is an upsert, so repeat calls are harmless.
    repo.save_job(workspace.conn, Job(job_id=job_id, input_file="m.mp4"))
    return sample_movie(
        workspace.source,
        SPANS,
        job_id=job_id,
        jobs_dir=workspace.jobs_dir,
        conn=workspace.conn,
        cache=workspace.cache,
        run_fn=_fake_run,
    )


# ---------------------------------------------------------------------------
# The reported failure
# ---------------------------------------------------------------------------


def test_new_job_reuses_frames_from_the_previous_job(
    workspace: _Workspace, counter: dict[str, int]
) -> None:
    """The regression: a fresh `process` run must not re-decode the movie."""
    first = _sample(workspace, "job_006")
    assert len(first.frames) == 9  # 3 for a 5s scene, 6 for a 30s scene
    after_first = counter["n"]

    second = _sample(workspace, "job_007")

    assert counter["n"] == after_first, "re-extracted frames that already existed"
    assert second.cache_hit is True
    assert [f.timestamp for f in second.frames] == [f.timestamp for f in first.frames]


def test_new_job_still_gets_its_own_frame_files(
    workspace: _Workspace, counter: dict[str, int]
) -> None:
    """Adoption copies; it must not leave the job depending on another directory.

    Jobs are deleted and archived independently, so sharing files across job
    directories would let one job's cleanup destroy another's data.
    """
    _sample(workspace, "job_006")

    second = _sample(workspace, "job_007")

    frames_dir = workspace.jobs_dir / "job_007" / "frames"
    assert all(f.path.is_file() for f in second.frames)
    assert all(f.path.parent.parent == frames_dir for f in second.frames)
    assert not any("job_006" in str(f.path) for f in second.frames)


def test_adopted_bytes_are_identical(workspace: _Workspace, counter: dict[str, int]) -> None:
    """A copy must be byte-identical, or the VLM sees different pixels."""
    first = _sample(workspace, "job_006")
    original = {f.timestamp: f.path.read_bytes() for f in first.frames}

    second = _sample(workspace, "job_007")

    assert {f.timestamp: f.path.read_bytes() for f in second.frames} == original


# ---------------------------------------------------------------------------
# A failed vision run leaves reusable frames behind
# ---------------------------------------------------------------------------


def _vision_ctx(workspace: _Workspace, job_id: str) -> PipelineContext:
    conn = workspace.conn
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id=job_id, input_file="m.mp4"))
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
    ):
        manager.transition(job_id, state)
    for index, (scene_id, start, end) in enumerate(SPANS):
        repo.save_scene(
            conn,
            job_id,
            Scene(
                scene_id=scene_id,
                start=start + index * 100,
                end=end + index * 100,
                duration=end - start,
            ),
        )
    return PipelineContext(
        job_id=job_id,
        movie_path=workspace.source,
        jobs_dir=workspace.jobs_dir,
        conn=conn,
        manager=manager,
        cache=workspace.cache,
        settings=load_settings(),
    )


def test_frames_survive_a_remote_failure_and_are_reused(
    workspace: _Workspace,
    counter: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
    stub_analysis_proxy: None,
) -> None:
    """The user's report, end to end: VLM 500 on run 1, no re-decode on run 2."""
    from movie_review.vision.port import VLMUnavailableError

    def failing(*_a: object, **_kw: object) -> None:
        raise VLMUnavailableError("Qwen3-VL", "HTTP 500 from /v1/chat/completions")

    monkeypatch.setattr("movie_review.vision.analysis.run_visual_analysis", failing)

    first = run_stage("vision", _vision_stage(), _vision_ctx(workspace, "job_006"))
    assert first.success is False
    after_first = counter["n"]
    assert after_first > 0

    monkeypatch.setattr(
        "movie_review.vision.analysis.run_visual_analysis", lambda *a, **kw: object()
    )
    second = run_stage("vision", _vision_stage(), _vision_ctx(workspace, "job_007"))

    assert second.success is True, second.error
    assert counter["n"] == after_first, "frames were re-sampled after the 500"


# ---------------------------------------------------------------------------
# Integrity: adoption must not launder a bad frame
# ---------------------------------------------------------------------------


def test_corrupt_source_frame_is_re_extracted(
    workspace: _Workspace, counter: dict[str, int]
) -> None:
    """Hash mismatch in the cached source means re-extract, never copy."""
    first = _sample(workspace, "job_006")
    first.frames[0].path.write_bytes(b"tampered")
    before = counter["n"]

    second = _sample(workspace, "job_007")

    assert counter["n"] > before, "adopted a frame whose bytes did not match"
    # The new job must hold freshly extracted bytes. The old job's copy is left
    # alone: adoption never rewrites another job's directory.
    assert second.frames[0].path.read_bytes() != b"tampered"


def test_missing_source_frame_is_re_extracted(
    workspace: _Workspace, counter: dict[str, int]
) -> None:
    first = _sample(workspace, "job_006")
    first.frames[0].path.unlink()
    before = counter["n"]

    second = _sample(workspace, "job_007")

    assert counter["n"] > before
    assert len(second.frames) == 9


def test_existing_destination_is_verified_not_overwritten_blindly(
    workspace: _Workspace, counter: dict[str, int]
) -> None:
    """A corrupted file already in the new job must be replaced, not trusted."""
    _sample(workspace, "job_006")
    dest = workspace.jobs_dir / "job_007" / "frames" / "scene_000001"
    dest.mkdir(parents=True, exist_ok=True)
    planted = dest / frames_module.frame_filename("scene_000001", 0.0)
    planted.write_bytes(b"not the real frame")
    before = counter["n"]

    _sample(workspace, "job_007")

    assert planted.read_bytes() != b"not the real frame"
    assert counter["n"] >= before


# ---------------------------------------------------------------------------
# Partial progress survives an interrupted sampling run
# ---------------------------------------------------------------------------


def test_interrupted_sampling_keeps_finished_scenes(
    workspace: _Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash after scene 1 must not cost scene 1 on the retry."""
    real = _REAL_EXTRACT

    def _flaky(
        source: str | Path,
        timestamp: float,
        dest: str | Path,
        ffmpeg: str = "ffmpeg",
        _ignored: object = None,
    ) -> Path:
        if Path(dest).parent.name == "scene_000002":
            raise RuntimeError("disk full")
        result: Path = real(source, timestamp, dest, ffmpeg, _fake_run)
        return result

    monkeypatch.setattr(frames_module, "extract_frame", _flaky)

    with pytest.raises(RuntimeError, match="disk full"):
        sample_movie(
            workspace.source,
            SPANS,
            job_id="job_interrupted",
            jobs_dir=workspace.jobs_dir,
            conn=workspace.conn,
            cache=workspace.cache,
            run_fn=_fake_run,
        )

    monkeypatch.undo()
    calls = {"n": 0}

    def _counting(
        source: str | Path,
        timestamp: float,
        dest: str | Path,
        ffmpeg: str = "ffmpeg",
        _ignored: object = None,
    ) -> Path:
        calls["n"] += 1
        return _REAL_EXTRACT(source, timestamp, dest, ffmpeg, _fake_run)

    monkeypatch.setattr(frames_module, "extract_frame", _counting)
    result = _sample(workspace, "job_after")

    assert len(result.frames) == 9
    assert calls["n"] == 6, "only scene_000002's 6 frames should be extracted"
    assert result.cache_hit is False, "a partly adopted run is not a cache hit"


# ---------------------------------------------------------------------------
# A malformed pointer contributes only what it can vouch for
# ---------------------------------------------------------------------------


def test_unreadable_pointer_entries_are_skipped_not_fatal(
    workspace: _Workspace, counter: dict[str, int]
) -> None:
    """One bad entry must not discard the scenes that are fine."""
    _sample(workspace, "job_006")
    key = frames_module.frames_cache_key(
        artifacts.sha256_file(workspace.source),
        SPANS,
        frames_module.SamplingConfig(),
    )
    pointer = workspace.cache.lookup_json(key)
    assert isinstance(pointer, dict)
    pointer["frames"].append({"scene_id": "scene_000009"})  # missing keys
    workspace.cache.store_json(key, pointer)
    before = counter["n"]

    result = _sample(workspace, "job_007")

    assert len(result.frames) == 9
    assert counter["n"] == before, "a malformed entry should not force a re-sample"


def test_empty_scene_list_is_a_cache_miss_not_an_error(
    workspace: _Workspace, counter: dict[str, int]
) -> None:
    repo.save_job(workspace.conn, Job(job_id="job_empty", input_file="m.mp4"))
    result = sample_movie(
        workspace.source,
        [],
        job_id="job_empty",
        jobs_dir=workspace.jobs_dir,
        conn=workspace.conn,
        cache=workspace.cache,
        run_fn=_fake_run,
    )
    assert result.frames == []
    assert result.cache_hit is False, "zero frames must not claim a cache hit"
    assert counter["n"] == 0
