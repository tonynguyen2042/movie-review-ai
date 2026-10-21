"""The vision stage must not be one round trip per scene.

T138 regression. The scenes were analysed in a strict loop, one VLM call
each. For a 2 h film that is about 1000 sequential calls, which at 3 s per
scene is fifty minutes of pure serial latency with the machine idle.

The scenes are now analysed in batches, and the scenes in a batch run
concurrently. The continuity context -- what the scene before showed -- comes
from the batch before, so it still crosses the scenes.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus, Scene, SceneAnalysis
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.vision.analysis import run_visual_analysis
from movie_review.vision.port import AnalysisInput, VLMPort


class _SlowAdapter(VLMPort):
    """An adapter that records how many calls overlapped."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.calls: list[str] = []
        self.max_overlap = 0
        self._active = 0
        self._lock = threading.Lock()

    @property
    def model(self) -> str:
        return "slow"

    def analyze(self, inputs: AnalysisInput, prompt: str) -> SceneAnalysis:
        with self._lock:
            self._active += 1
            self.max_overlap = max(self.max_overlap, self._active)
            self.calls.append(inputs.scene_id)
        try:
            time.sleep(self.delay)
            return SceneAnalysis(
                scene_id=inputs.scene_id,
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
                self._active -= 1

    def unload(self) -> None:
        return None

    def available(self) -> bool:
        return True


def _ctx(tmp_path: Path) -> tuple[StageContext, sqlite3.Connection]:
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
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
    )
    return ctx, conn


def _scenes(count: int) -> list[Scene]:
    return [
        Scene(
            scene_id=f"scene_{index:06d}",
            start=float(index * 10),
            end=float(index * 10 + 9),
            duration=9.0,
        )
        for index in range(count)
    ]


def _frames(tmp_path: Path, scenes: list[Scene]) -> dict[str, list[Path]]:
    frames: dict[str, list[Path]] = {}
    for scene in scenes:
        path = tmp_path / scene.scene_id / "frame.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00" * 32)
        frames[scene.scene_id] = [path]
    return frames


def test_the_scenes_of_a_batch_are_analysed_concurrently(tmp_path: Path) -> None:
    """More than one call must be in flight at the same time."""
    ctx, conn = _ctx(tmp_path)
    try:
        scenes = _scenes(8)
        adapter = _SlowAdapter()
        result = run_visual_analysis(
            scenes,
            _frames(tmp_path, scenes),
            [],
            ctx,
            port=adapter,
            batch_size=8,
        )
        assert len(result.analyses) == 8
        assert adapter.max_overlap > 1, "the calls did not overlap"
    finally:
        conn.close()


def test_the_results_keep_the_scene_order(tmp_path: Path) -> None:
    """Concurrency must not reorder the analyses."""
    ctx, conn = _ctx(tmp_path)
    try:
        scenes = _scenes(8)
        adapter = _SlowAdapter()
        result = run_visual_analysis(
            scenes,
            _frames(tmp_path, scenes),
            [],
            ctx,
            port=adapter,
            batch_size=8,
        )
        assert [a.scene_id for a in result.analyses] == [s.scene_id for s in scenes]
    finally:
        conn.close()


def test_the_continuity_context_comes_from_the_previous_batch(tmp_path: Path) -> None:
    """The scene after a batch must be told what the batch showed."""
    ctx, conn = _ctx(tmp_path)
    prompts: list[str] = []

    class _Recording(_SlowAdapter):
        def analyze(self, inputs: AnalysisInput, prompt: str) -> SceneAnalysis:
            prompts.append(prompt)
            return super().analyze(inputs, prompt)

    try:
        scenes = _scenes(4)
        result = run_visual_analysis(
            scenes,
            _frames(tmp_path, scenes),
            [],
            ctx,
            port=_Recording(),
            batch_size=2,
        )
        assert len(prompts) == 4
        # The first batch is told there is no previous scene.
        assert "none (first scene)" in prompts[0]
        # The second batch is told about the last scene of the first.
        assert "here: something happens" in prompts[2]
        assert len(result.analyses) == 4
    finally:
        conn.close()


def test_a_failure_in_one_scene_fails_the_stage(tmp_path: Path) -> None:
    """A broken scene must fail the stage, not be skipped."""
    ctx, conn = _ctx(tmp_path)
    try:
        scenes = _scenes(4)

        class _Broken(_SlowAdapter):
            def analyze(self, inputs: AnalysisInput, prompt: str) -> SceneAnalysis:
                if inputs.scene_id == "scene_000002":
                    raise RuntimeError("the model fell over")
                return super().analyze(inputs, prompt)

        from movie_review.vision.analysis import VisualAnalysisError

        try:
            run_visual_analysis(
                scenes,
                _frames(tmp_path, scenes),
                [],
                ctx,
                port=_Broken(),
                batch_size=4,
            )
        except VisualAnalysisError as exc:
            assert "scene_000002" in str(exc)
        else:
            raise AssertionError("the stage should have failed")
    finally:
        conn.close()
