"""T181 acceptance: a request never carries more frames than the cap allows.

A scene keeps every frame it sampled, but an endpoint -- a remote one in
particular -- may refuse more images than its budget in a single request.
Over the cap, the request keeps the first and the last frame and spaces the
rest evenly; the cap is configuration and joins the per-scene cache key.
"""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import ModelSpec, load_settings
from movie_review.domain import Job, JobStatus, Scene, SceneAnalysis
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.orchestrator import PipelineContext, _get_stage_function
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.vision.analysis import (
    VisualAnalysisError,
    _request_frames,
    run_visual_analysis,
)
from movie_review.vision.port import AnalysisInput, VLMPort

frames_module = importlib.import_module("movie_review.media.frames")


class _RecordingAdapter(VLMPort):
    """A port that records exactly what each request carries."""

    def __init__(self) -> None:
        self.inputs: list[AnalysisInput] = []
        self.prompts: list[str] = []

    @property
    def model(self) -> str:
        return "rec"

    def analyze(self, analysis_input: AnalysisInput, prompt: str) -> SceneAnalysis:
        self.inputs.append(analysis_input)
        self.prompts.append(prompt)
        return SceneAnalysis(
            scene_id=analysis_input.scene_id,
            location="here",
            characters=[],
            actions=["something happens"],
            objects=[],
            emotions=[],
            visual_events=[],
            importance=0.5,
        )

    def unload(self) -> None:
        return None

    def available(self) -> bool:
        return True


def _ctx__vision_max_frames(tmp_path: Path) -> tuple[PipelineContext, sqlite3.Connection]:
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
    ctx = PipelineContext(
        job_id="job_1",
        movie_path=source,
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
    )
    return ctx, conn


def _frames__vision_max_frames(tmp_path: Path, count: int) -> dict[str, list[Path]]:
    directory = tmp_path / "scene_000001"
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(count):
        path = directory / f"f{index:02d}.jpg"
        path.write_bytes(f"frame-{index}".encode())
        paths.append(path)
    return {"scene_000001": paths}


def _scene__vision_max_frames() -> Scene:
    return Scene(scene_id="scene_000001", start=0.0, end=20.0, duration=20.0)


# ---------------------------------------------------------------------------
# The subset itself
# ---------------------------------------------------------------------------


def test_request_frames_under_the_cap_is_unchanged(tmp_path: Path) -> None:
    paths = list(_frames__vision_max_frames(tmp_path, 3).values())[0]
    assert _request_frames(paths, 8) == paths
    assert _request_frames(paths, 3) == paths  # exactly at the cap: nothing cut
    assert _request_frames([], 8) == []


def test_request_frames_over_the_cap_keeps_the_ends_and_is_chronological(
    tmp_path: Path,
) -> None:
    paths = list(_frames__vision_max_frames(tmp_path, 20).values())[0]
    subset = _request_frames(paths, 8)

    # Twenty frames, cap of eight: step 19/7, rounded to these indices.
    assert [path.name for path in subset] == [
        "f00.jpg",
        "f03.jpg",
        "f05.jpg",
        "f08.jpg",
        "f11.jpg",
        "f14.jpg",
        "f16.jpg",
        "f19.jpg",
    ]
    assert subset[0] is paths[0]  # the scene opens on its first frame
    assert subset[-1] is paths[-1]  # and closes on its last


def test_request_frames_single_frame_cap_keeps_the_middle(tmp_path: Path) -> None:
    paths = list(_frames__vision_max_frames(tmp_path, 5).values())[0]
    assert _request_frames(paths, 1) == [paths[2]]


# ---------------------------------------------------------------------------
# The stage honours the cap
# ---------------------------------------------------------------------------


def test_the_request_never_carries_more_than_the_cap(tmp_path: Path) -> None:
    ctx, conn = _ctx__vision_max_frames(tmp_path)
    try:
        adapter = _RecordingAdapter()
        result = run_visual_analysis(
            [_scene__vision_max_frames()],
            _frames__vision_max_frames(tmp_path, 20),
            [],
            ctx,
            port=adapter,
            max_frames=8,
        )
        assert len(result.analyses) == 1
        assert len(adapter.inputs) == 1
        assert len(adapter.inputs[0].frames) == 8
    finally:
        conn.close()


def test_under_the_cap_the_request_is_unchanged(tmp_path: Path) -> None:
    ctx, conn = _ctx__vision_max_frames(tmp_path)
    try:
        adapter = _RecordingAdapter()
        all_paths = list(_frames__vision_max_frames(tmp_path, 3).values())[0]
        run_visual_analysis(
            [_scene__vision_max_frames()],
            _frames__vision_max_frames(tmp_path, 3),
            [],
            ctx,
            port=adapter,
            max_frames=8,
        )
        assert adapter.inputs[0].frames == all_paths
        assert "3 frames" in adapter.prompts[0]
    finally:
        conn.close()


def test_the_prompt_describes_the_frames_sent(tmp_path: Path) -> None:
    ctx, conn = _ctx__vision_max_frames(tmp_path)
    try:
        adapter = _RecordingAdapter()
        run_visual_analysis(
            [_scene__vision_max_frames()],
            _frames__vision_max_frames(tmp_path, 20),
            [],
            ctx,
            port=adapter,
            max_frames=8,
        )
        # The prompt promises the frames the request actually carries.
        assert "8 frames" in adapter.prompts[0]
        assert "20 frames" not in adapter.prompts[0]
    finally:
        conn.close()


def test_the_cap_joins_the_cache_key(tmp_path: Path) -> None:
    ctx, conn = _ctx__vision_max_frames(tmp_path)
    try:
        adapter = _RecordingAdapter()
        scene = _scene__vision_max_frames()

        frames_20 = _frames__vision_max_frames(tmp_path, 20)
        run_visual_analysis([scene], frames_20, [], ctx, port=adapter, max_frames=8)
        # A different cap means a different subset, so the scene is re-analysed
        # rather than adopting the other cap's answer.
        run_visual_analysis([scene], frames_20, [], ctx, port=adapter, max_frames=12)
        # The original cap is cached again: no third call.
        run_visual_analysis([scene], frames_20, [], ctx, port=adapter, max_frames=8)

        assert len(adapter.inputs) == 2
        assert [len(entry.frames) for entry in adapter.inputs] == [8, 12]
    finally:
        conn.close()


def test_an_invalid_cap_is_rejected(tmp_path: Path) -> None:
    ctx, conn = _ctx__vision_max_frames(tmp_path)
    try:
        with pytest.raises(VisualAnalysisError, match="at least 1"):
            run_visual_analysis(
                [_scene__vision_max_frames()],
                _frames__vision_max_frames(tmp_path, 3),
                [],
                ctx,
                port=_RecordingAdapter(),
                max_frames=0,
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The cap is configuration, and the orchestrator passes it
# ---------------------------------------------------------------------------


def test_the_cap_comes_from_the_model_spec() -> None:
    assert ModelSpec(model="m").max_frames_per_request == 32
    assert ModelSpec(model="m", max_frames_per_request=7).max_frames_per_request == 7
    with pytest.raises(ValueError):
        ModelSpec(model="m", max_frames_per_request=0)


def test_the_orchestrator_passes_the_configured_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_analysis_proxy: None,
) -> None:
    ctx, conn = _ctx__vision_max_frames(tmp_path)
    try:
        repo.save_scene(ctx.conn, ctx.job_id, _scene__vision_max_frames())

        # The stage's frame preparation must not shell out to ffmpeg.
        def _fake_extract(
            source: str | Path,
            timestamp: float,
            dest: str | Path,
            ffmpeg: str = "ffmpeg",
            _ignored_run_fn: Any = None,
        ) -> Path:
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"frame-bytes")
            return dest

        monkeypatch.setattr(frames_module, "extract_frame", _fake_extract)

        seen: list[int] = []

        def _spy(
            scenes: Any,
            frames: Any,
            segments: Any,
            stage_ctx: Any,
            port: Any = None,
            prompt_version: Any = None,
            on_progress: Any = None,
            max_frames: int = 32,
            **_kwargs: Any,
        ) -> Any:
            seen.append(max_frames)
            return None

        monkeypatch.setattr("movie_review.vision.analysis.run_visual_analysis", _spy)

        stage = _get_stage_function("vision")
        assert stage is not None

        # The configured default reaches the stage.
        stage(ctx)
        assert seen == [32]

        # An operator-set cap reaches the stage too.
        ctx.settings.models.vision.max_frames_per_request = 7
        stage(ctx)
        assert seen == [32, 7]
    finally:
        conn.close()
