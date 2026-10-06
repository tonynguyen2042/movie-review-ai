"""The vision stage must actually have frames (T101).

``run_visual_analysis`` raises ``No frames for <scene>`` when a scene has no
frames, and the orchestrator passed an empty dict with a "for now empty" comment,
so the vision stage failed on its first scene every time -- before any model was
involved.

``sample_movie`` existed, was idempotent, cache-verified against per-frame
sha256, and had no production caller. These tests pin the wiring at the
orchestrator, which is where the gap was: they run the real stage function and
assert on the frames it hands to the analysis.

ffmpeg is replaced with a stub that writes the output file, so the tests assert
the wiring rather than the encoder.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus, Scene
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.orchestrator import PipelineContext, _get_stage_function
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect

# `import movie_review.cli.app as m` style trap: package __init__ re-exports.
frames_module = importlib.import_module("movie_review.media.frames")

MINIMAL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)

#: Captured before any patching. extract_frame binds ``run_fn=ff.check`` as a
#: default argument at definition time, so patching ff.check cannot redirect it.
_real_extract_frame = frames_module.extract_frame


def _fake_run(binary: str, args: list[str]) -> str:
    """Stand in for ffmpeg: write something at the output path."""
    dest = Path(args[-1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(MINIMAL_PNG)
    return ""


def _extract_with(run_fn: Callable[..., str]) -> Callable[..., Path]:
    """Force extract_frame's run_fn to a stub, delegating to the real one.

    sample_movie passes its own ``run_fn`` (ff.check by default) as the fifth
    positional argument, so a wrapper that merely defaulted to the stub would
    forward the real check straight through and shell out to ffmpeg. The
    caller's value is discarded on purpose.
    """

    def _extract(
        source: str | Path,
        timestamp: float,
        dest: str | Path,
        ffmpeg: str = "ffmpeg",
        _ignored_run_fn: Any = None,
    ) -> Path:
        result: Path = _real_extract_frame(source, timestamp, dest, ffmpeg, run_fn)
        return result

    return _extract


@pytest.fixture
def ctx(tmp_path: Path) -> PipelineContext:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
    ):
        manager.transition("job_1", state)

    source = tmp_path / "m.mp4"
    source.write_bytes(b"source-bytes")

    return PipelineContext(
        job_id="job_1",
        movie_path=source,
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
    )


def _scenes(ctx: PipelineContext, spans: list[tuple[str, float, float]]) -> None:
    for scene_id, start, end in spans:
        repo.save_scene(
            ctx.conn,
            ctx.job_id,
            Scene(scene_id=scene_id, start=start, end=end, duration=end - start),
        )


def _vision_stage() -> Callable[[PipelineContext], Any]:
    stage = _get_stage_function("vision")
    assert stage is not None, "vision stage is missing from the orchestrator"
    return stage


@pytest.fixture
def captured_frames(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, list[Path]]]:
    """Capture what the stage hands to the analysis, and answer with a stub."""
    seen: list[dict[str, list[Path]]] = []

    monkeypatch.setattr(frames_module, "extract_frame", _extract_with(_fake_run))

    def fake_run_visual_analysis(
        scenes: Any,
        frames: dict[str, list[Path]],
        segments: Any,
        stage_ctx: Any,
        port: Any = None,
        prompt_version: Any = None,
    ) -> object:
        seen.append(frames)
        return object()

    import movie_review.vision.analysis as vision_analysis

    monkeypatch.setattr(vision_analysis, "run_visual_analysis", fake_run_visual_analysis)
    return seen


# ---------------------------------------------------------------------------
# Frames reach the analysis
# ---------------------------------------------------------------------------


def test_vision_stage_samples_frames(ctx: PipelineContext, captured_frames: list[Any]) -> None:
    """The stage that failed on its first scene must now supply frames."""
    _scenes(ctx, [("scene_000001", 0.0, 5.0), ("scene_000002", 5.0, 35.0)])

    _vision_stage()(ctx)

    assert len(captured_frames) == 1
    frames: dict[str, list[Path]] = captured_frames[0]
    assert set(frames) == {"scene_000001", "scene_000002"}
    assert all(len(paths) >= 2 for paths in frames.values()), "every scene needs >= 2 frames"
    assert all(path.is_file() for paths in frames.values() for path in paths)


def test_frames_are_ordered_within_a_scene(
    ctx: PipelineContext, captured_frames: list[Any]
) -> None:
    """The VLM reads frames as a sequence; timestamp order is the sequence."""
    _scenes(ctx, [("scene_000001", 0.0, 30.0)])

    _vision_stage()(ctx)

    frames: dict[str, list[Path]] = captured_frames[0]
    names = [p.name for p in frames["scene_000001"]]
    stamps = [int(n.rsplit("-", 1)[1].split(".")[0]) for n in names]
    assert stamps == sorted(stamps), f"frames out of order: {names}"


def test_frame_counts_follow_the_configured_buckets(
    ctx: PipelineContext, captured_frames: list[Any]
) -> None:
    """Short/medium/long buckets must reach the stage, not just the module."""
    # default.yaml: short_threshold 10, medium_threshold 60, 3/6/12 frames
    _scenes(
        ctx,
        [
            ("scene_000001", 0.0, 5.0),  # short  -> 3
            ("scene_000002", 10.0, 40.0),  # medium -> 6
            ("scene_000003", 60.0, 200.0),  # long   -> 12
        ],
    )

    _vision_stage()(ctx)

    frames: dict[str, list[Path]] = captured_frames[0]
    assert len(frames["scene_000001"]) == 3
    assert len(frames["scene_000002"]) == 6
    assert len(frames["scene_000003"]) == 12


def test_no_scenes_yields_no_frames(ctx: PipelineContext, captured_frames: list[Any]) -> None:
    """Degenerate input must not raise from the sampler."""
    _vision_stage()(ctx)

    assert captured_frames == [{}]


# ---------------------------------------------------------------------------
# Idempotency: a retry must not re-run ffmpeg
# ---------------------------------------------------------------------------


def test_second_vision_run_reuses_cached_frames(
    ctx: PipelineContext, captured_frames: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming or retrying vision must not re-extract every frame.

    A retry after a failed vision run is the common case, and re-running ffmpeg
    over hundreds of scenes to reach the same result is the difference between
    seconds and many minutes.
    """
    _scenes(ctx, [("scene_000001", 0.0, 5.0)])

    stage = _vision_stage()
    stage(ctx)
    first = [p.name for p in captured_frames[0]["scene_000001"]]

    calls: list[int] = []

    def _counting(binary: str, args: list[str]) -> str:
        calls.append(1)
        return _fake_run(binary, args)

    monkeypatch.setattr(frames_module, "extract_frame", _extract_with(_counting))
    stage(ctx)

    assert calls == [], f"ffmpeg ran {len(calls)} times on a cached rerun"
    assert [p.name for p in captured_frames[1]["scene_000001"]] == first


# ---------------------------------------------------------------------------
# A sampling failure must be reported, not swallowed
# ---------------------------------------------------------------------------


def test_frame_extraction_failure_fails_the_stage(
    ctx: PipelineContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ffmpeg cannot extract a frame, the stage must say so."""
    from movie_review.media import ffmpeg as ff
    from movie_review.media.frames import FrameSamplingError

    _scenes(ctx, [("scene_000001", 0.0, 5.0)])

    def _boom(binary: str, args: list[str]) -> str:
        raise ff.ProcessError(binary, args, "boom")

    monkeypatch.setattr(frames_module, "extract_frame", _extract_with(_boom))

    with pytest.raises(FrameSamplingError, match="Cannot extract frame"):
        _vision_stage()(ctx)
