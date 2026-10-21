"""T025 acceptance: visual analysis stage wires frames, dialogue, and VLM."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus, Scene, SceneAnalysis, TranscriptSegment
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.vision.analysis import (
    VisualAnalysisError,
    VisualAnalysisResult,
    previous_summary,
    run_visual_analysis,
    scene_dialogue,
)
from movie_review.vision.port import AnalysisInput, VLMPort


class _FakeVLM(VLMPort):
    def __init__(self) -> None:
        self.calls: list[AnalysisInput] = []
        self.prompts: list[str] = []
        self.unloaded = False
        self.fail_on: str | None = None

    def analyze(self, analysis_input: AnalysisInput, prompt: str) -> SceneAnalysis:
        if self.fail_on == analysis_input.scene_id:
            raise RuntimeError("backend exploded")
        self.calls.append(analysis_input)
        self.prompts.append(prompt)
        return SceneAnalysis(
            scene_id=analysis_input.scene_id,
            location=f"loc-{analysis_input.scene_id}",
            actions=[f"act-{analysis_input.scene_id}"],
        )

    def unload(self) -> None:
        self.unloaded = True


@dataclass
class Harness:
    conn: sqlite3.Connection
    ctx: StageContext
    port: _FakeVLM
    scenes: list[Scene]
    frames: dict[str, list[Path]]
    segments: list[TranscriptSegment]

    def stage(self, batch_size: int = 8) -> VisualAnalysisResult:
        return run_visual_analysis(
            self.scenes,
            self.frames,
            self.segments,
            self.ctx,
            port=self.port,
            batch_size=batch_size,
        )


def _harness(tmp_path: Path) -> Harness:
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
    frames: dict[str, list[Path]] = {}
    for scene_id in ("scene_000001", "scene_000002"):
        scene_dir = tmp_path / "frames" / scene_id
        scene_dir.mkdir(parents=True)
        paths = []
        for index in range(2):
            path = scene_dir / f"f{index}.jpg"
            path.write_bytes(b"frame-bytes")
            paths.append(path)
        frames[scene_id] = paths
    scenes = [
        Scene(scene_id="scene_000001", start=0.0, end=10.0, duration=10.0),
        Scene(scene_id="scene_000002", start=10.0, end=20.0, duration=10.0),
    ]
    segments = [
        TranscriptSegment(
            segment_id="seg_1", start=1.0, end=3.0, text="first lines", language="en"
        ),
        TranscriptSegment(
            segment_id="seg_2", start=12.0, end=14.0, text="second lines", language="en"
        ),
    ]
    port = _FakeVLM()
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )
    return Harness(conn=conn, ctx=ctx, port=port, scenes=scenes, frames=frames, segments=segments)


def test_stage_happy_path(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    result = harness.stage()
    assert [a.scene_id for a in result.analyses] == ["scene_000001", "scene_000002"]
    assert result.cache_hits == 0
    assert result.vision_path.is_file()
    assert harness.port.unloaded is True
    assert harness.ctx.manager.get("job_1").status is JobStatus.VISUAL_ANALYSIS_READY
    assert repo.get_artifact(harness.conn, "job_1-vision") is not None
    # The scenes of a batch run concurrently, so the calls are not in order.
    # Each scene must still get its own dialogue.
    by_scene = {call.scene_id: call for call in harness.port.calls}
    assert by_scene["scene_000001"].dialogue == "first lines"
    assert by_scene["scene_000002"].dialogue == "second lines"


def test_scene_sees_the_previous_scene_summary(tmp_path: Path) -> None:
    """A scene is told what the scene before it showed.

    The scenes are analysed in batches, and the continuity context comes from
    the batch before, so a batch of one is the serial behaviour.
    """
    harness = _harness(tmp_path)
    harness.stage(batch_size=1)
    by_scene = {call.scene_id: call for call in harness.port.calls}
    assert "loc-scene_000001" in (by_scene["scene_000002"].previous_summary or "")


def test_stage_second_run_hits_cache(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.stage()
    harness.port.calls.clear()
    result = harness.stage()
    assert result.cache_hits == 2
    assert harness.port.calls == []


def test_stage_unknown_job(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.ctx.job_id = "job_2"
    with pytest.raises(VisualAnalysisError, match="Unknown job"):
        harness.stage()


def test_stage_failed_job_rejected(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.ctx.manager.fail("job_1", "transcript", "earlier")
    with pytest.raises(VisualAnalysisError, match="failed"):
        harness.stage()


def test_stage_vlm_failure_fails_job(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.port.fail_on = "scene_000002"
    with pytest.raises(VisualAnalysisError, match="Cannot analyze scene_000002"):
        harness.stage()
    job = harness.ctx.manager.get("job_1")
    assert job.status is JobStatus.FAILED
    assert "scene_000002" in (job.error or "")
    assert harness.port.unloaded is True


def test_stage_missing_frames_rejected(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.frames.pop("scene_000002")
    with pytest.raises(VisualAnalysisError, match="No frames"):
        harness.stage()


def test_stage_rerun_past_ready(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.stage()
    harness.ctx.manager.transition("job_1", JobStatus.CHARACTERS_READY)
    result = harness.stage()
    assert result.cache_hits == 2
    assert harness.ctx.manager.get("job_1").status is JobStatus.CHARACTERS_READY


def test_scene_dialogue_overlap_and_truncation() -> None:
    segments = [
        TranscriptSegment(segment_id="a", start=0.0, end=5.0, text="in"),
        TranscriptSegment(segment_id="b", start=4.0, end=9.0, text="edge"),
        TranscriptSegment(segment_id="c", start=20.0, end=21.0, text="out"),
    ]
    assert scene_dialogue(segments, 0.0, 10.0) == "in edge"
    assert scene_dialogue(segments, 30.0, 40.0) == ""
    long_text = "x" * 3000
    long_seg = TranscriptSegment(segment_id="d", start=0.0, end=1.0, text=long_text)
    assert scene_dialogue([long_seg], 0.0, 2.0).endswith("…")


def test_previous_summary() -> None:
    assert previous_summary(None) == "none (first scene)"
    analysis = SceneAnalysis(scene_id="s", location="dock", actions=["runs", "hides"])
    assert previous_summary(analysis) == "dock: runs; hides"
