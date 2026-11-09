"""T185 acceptance: vision concurrency is configuration, not a constant.

The vision stage's in-flight budget used to be hard-coded to 4, so an
operator on a remote endpoint that serves requests in flight could not use
that parallelism. ``pipeline.visual_analysis.concurrency`` now carries the
value: the stage honours it, and the orchestrator's vision stage passes the
configured number through to ``run_visual_analysis``.
"""

from __future__ import annotations

import hashlib
import importlib
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings, read_yaml, repo_root
from movie_review.domain import Job, JobStatus, Scene, SceneAnalysis
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.orchestrator import PipelineContext, _get_stage_function
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.vision.analysis import (
    DEFAULT_CONCURRENCY,
    VisualAnalysisError,
    run_visual_analysis,
)
from movie_review.vision.port import AnalysisInput, VLMPort

frames_module = importlib.import_module("movie_review.media.frames")
fingerprint_module = importlib.import_module("movie_review.media.fingerprint")


class _InFlightVlm__vision_concurrency(VLMPort):
    """A port that measures how many of its calls overlap."""

    def __init__(self, hold_seconds: float = 0.05) -> None:
        self._hold = hold_seconds
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0

    @property
    def model(self) -> str:
        return "rec"

    def analyze(self, analysis_input: AnalysisInput, prompt: str) -> SceneAnalysis:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            time.sleep(self._hold)
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
        finally:
            with self._lock:
                self._in_flight -= 1

    def unload(self) -> None:
        return None

    def available(self) -> bool:
        return True


def _ctx__vision_concurrency(
    tmp_path: Path, settings: Any = None
) -> tuple[PipelineContext, sqlite3.Connection]:
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
        settings=settings if settings is not None else load_settings(),
    )
    return ctx, conn


def _scenes__vision_concurrency(count: int) -> list[Scene]:
    scenes = []
    for index in range(count):
        start = index * 10.0
        scenes.append(
            Scene(scene_id=f"scene_{index:06d}", start=start, end=start + 10.0, duration=10.0)
        )
    return scenes


def _frames__vision_concurrency(count: int, tmp_path: Path) -> dict[str, list[Path]]:
    frames: dict[str, list[Path]] = {}
    for index in range(count):
        directory = tmp_path / "frames" / f"scene_{index:06d}"
        directory.mkdir(parents=True, exist_ok=True)
        paths = []
        for frame_index in range(2):
            path = directory / f"f{frame_index:02d}.jpg"
            path.write_bytes(f"scene-{index}-frame-{frame_index}".encode())
            paths.append(path)
        frames[f"scene_{index:06d}"] = paths
    return frames


# ---------------------------------------------------------------------------
# The configuration
# ---------------------------------------------------------------------------


def test_the_config_default_is_the_stage_default() -> None:
    """The settings fallback, the stage constant and the file all say four."""
    settings = load_settings()
    assert settings.pipeline.visual_analysis.concurrency == DEFAULT_CONCURRENCY == 4
    document = read_yaml(repo_root() / "config" / "config.yaml")
    assert document["pipeline"]["visual_analysis"]["concurrency"] == 4


# ---------------------------------------------------------------------------
# The stage honours the value
# ---------------------------------------------------------------------------


def test_a_configured_concurrency_caps_the_in_flight_calls(tmp_path: Path) -> None:
    """Six scenes, one batch, a budget of two: no third call ever starts."""
    ctx, conn = _ctx__vision_concurrency(tmp_path)
    try:
        adapter = _InFlightVlm__vision_concurrency()
        run_visual_analysis(
            _scenes__vision_concurrency(6),
            _frames__vision_concurrency(6, tmp_path),
            [],
            ctx,
            port=adapter,
            concurrency=2,
        )
        # Two workers, six calls each holding 50 ms: the second is in flight
        # before the first finishes, and the pool never opens a third.
        assert adapter.max_in_flight == 2
    finally:
        conn.close()


def test_concurrency_one_keeps_the_batch_serial(tmp_path: Path) -> None:
    ctx, conn = _ctx__vision_concurrency(tmp_path)
    try:
        adapter = _InFlightVlm__vision_concurrency()
        run_visual_analysis(
            _scenes__vision_concurrency(4),
            _frames__vision_concurrency(4, tmp_path),
            [],
            ctx,
            port=adapter,
            concurrency=1,
        )
        assert adapter.max_in_flight == 1
    finally:
        conn.close()


def test_a_zero_concurrency_is_rejected(tmp_path: Path) -> None:
    ctx, conn = _ctx__vision_concurrency(tmp_path)
    try:
        with pytest.raises(VisualAnalysisError, match="concurrency"):
            run_visual_analysis(
                _scenes__vision_concurrency(1),
                _frames__vision_concurrency(1, tmp_path),
                [],
                ctx,
                port=_InFlightVlm__vision_concurrency(),
                concurrency=0,
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The orchestrator passes the configured value through
# ---------------------------------------------------------------------------


MINIMAL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)

#: Captured before any patching. extract_frame binds ``run_fn=ff.check`` as a
#: default argument at definition time, so patching ff.check cannot redirect it.
_real_extract_frame = frames_module.extract_frame


def _fake_run__vision_concurrency(binary: str, args: list[str]) -> str:
    """Stand in for ffmpeg: write something at the output path."""
    dest = Path(args[-1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(MINIMAL_PNG)
    return ""


def _extract_with__vision_concurrency(
    run_fn: Any,
) -> Any:
    """Force extract_frame's run_fn to a stub, discarding the caller's value."""

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


def _fake_fingerprint__vision_concurrency(paths: list[Path], **_kwargs: Any) -> list[int]:
    """One far-apart hash per frame, so the dedupe keeps every sampled frame."""
    return [
        int.from_bytes(hashlib.sha256(str(path).encode()).digest()[:8], "big") for path in paths
    ]


def test_the_orchestrator_passes_the_configured_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_analysis_proxy: None,
) -> None:
    """The real stage function hands the file's value to the analysis."""
    settings = load_settings()
    pipeline = settings.pipeline.model_copy(
        update={
            "visual_analysis": settings.pipeline.visual_analysis.model_copy(
                update={"concurrency": 7}
            )
        }
    )
    settings = settings.model_copy(update={"pipeline": pipeline})
    ctx, conn = _ctx__vision_concurrency(tmp_path, settings)
    try:
        monkeypatch.setattr(
            frames_module,
            "extract_frame",
            _extract_with__vision_concurrency(_fake_run__vision_concurrency),
        )
        monkeypatch.setattr(
            fingerprint_module, "fingerprint_frames", _fake_fingerprint__vision_concurrency
        )

        calls: list[dict[str, Any]] = []

        def spy(scenes: Any, frames: Any, segments: Any, stage_ctx: Any, **kwargs: Any) -> object:
            calls.append(kwargs)
            return object()

        monkeypatch.setattr("movie_review.vision.analysis.run_visual_analysis", spy)

        stage = _get_stage_function("vision")
        assert stage is not None, "vision stage is missing from the orchestrator"
        for index in (0, 1):
            start = index * 35.0
            repo.save_scene(
                ctx.conn,
                ctx.job_id,
                Scene(scene_id=f"scene_{index:06d}", start=start, end=start + 35.0, duration=35.0),
            )

        stage(ctx)

        assert calls, "the stage never reached the analysis"
        assert all(call.get("concurrency") == 7 for call in calls)
    finally:
        conn.close()
