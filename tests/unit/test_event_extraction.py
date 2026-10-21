"""T033 acceptance (part 2): event extraction stage with a fake reasoner."""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Character, Job, JobStatus, Scene, SceneAnalysis, TranscriptSegment
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.reasoning.port import ReasoningPort
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.story.events import EventExtractionError, EventsResult, run_event_extraction


class _FakeReasoner(ReasoningPort):
    def __init__(self, outputs: list[object]) -> None:
        self._outputs = outputs
        self.calls = 0
        self.unloaded = False

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        self.calls += 1
        return json.dumps(self._outputs.pop(0))

    def unload(self) -> None:
        self.unloaded = True


@dataclass
class Harness:
    conn: sqlite3.Connection
    ctx: StageContext
    reasoner: _FakeReasoner
    scenes: list[Scene]

    def stage(self) -> EventsResult:
        return run_event_extraction(
            self.scenes,
            {
                "scene_000001": SceneAnalysis(scene_id="scene_000001", location="dock"),
                "scene_000002": SceneAnalysis(scene_id="scene_000002", location="ship"),
            },
            [
                TranscriptSegment(
                    segment_id="seg_1", start=1.0, end=2.0, text="Look!", language="en"
                )
            ],
            [Character(id="char_001", name="John", first_seen=0.0, last_seen=100.0)],
            self.ctx,
            reasoner=self.reasoner,
        )


def _harness__event_extraction(tmp_path: Path, outputs: list[object]) -> Harness:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
        JobStatus.VISUAL_ANALYSIS_READY,
        JobStatus.CHARACTERS_READY,
    ):
        manager.transition("job_1", state)
    scenes = [
        Scene(scene_id="scene_000001", start=0.0, end=10.0, duration=10.0),
        Scene(scene_id="scene_000002", start=10.0, end=20.0, duration=10.0),
    ]
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )
    return Harness(conn=conn, ctx=ctx, reasoner=_FakeReasoner(outputs), scenes=scenes)


def _later_first() -> list[object]:
    return [
        [
            {
                "type": "CLIMAX",
                "timestamp": 15.0,
                "characters": ["char_001"],
                "description": "Confrontation.",
                "importance": 0.95,
                "evidence": ["scene_000002"],
            }
        ],
        [
            {
                "type": "DISCOVERY",
                "timestamp": 5.0,
                "characters": ["char_001"],
                "description": "Finds a photo.",
                "importance": 0.8,
                "evidence": ["scene_000001"],
            }
        ],
    ]


def test_stage_orders_and_ids_events(tmp_path: Path) -> None:
    harness = _harness__event_extraction(tmp_path, _later_first())
    result = harness.stage()
    assert [(e.id, e.type.value) for e in result.events] == [
        ("event_00001", "DISCOVERY"),
        ("event_00002", "CLIMAX"),
    ]
    assert result.cache_hits == 0
    assert result.events_path.is_file()
    assert harness.reasoner.unloaded is True
    assert harness.ctx.manager.get("job_1").status is JobStatus.EVENTS_READY
    assert [e.id for e in repo.list_events(harness.conn, "job_1")] == [
        "event_00001",
        "event_00002",
    ]
    assert repo.get_artifact(harness.conn, "job_1-events") is not None


def test_stage_second_run_hits_cache(tmp_path: Path) -> None:
    harness = _harness__event_extraction(tmp_path, _later_first())
    harness.stage()
    harness.reasoner = _FakeReasoner([])
    result = harness.stage()
    assert result.cache_hits == 2


def test_stage_unknown_job(tmp_path: Path) -> None:
    harness = _harness__event_extraction(tmp_path, [[], []])
    harness.ctx.job_id = "job_2"
    with pytest.raises(EventExtractionError, match="Unknown job"):
        harness.stage()


def test_stage_failed_job_rejected(tmp_path: Path) -> None:
    harness = _harness__event_extraction(tmp_path, [[], []])
    harness.ctx.manager.fail("job_1", "vision", "earlier")
    with pytest.raises(EventExtractionError, match="failed"):
        harness.stage()


def test_stage_reasoner_failure_fails_job(tmp_path: Path) -> None:
    harness = _harness__event_extraction(tmp_path, [[{"type": "BROKEN"}]])

    class _Bad(_FakeReasoner):
        def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
            raise RuntimeError("backend exploded")

    harness.reasoner = _Bad([])
    with pytest.raises(EventExtractionError, match="Cannot extract events"):
        harness.stage()
    job = harness.ctx.manager.get("job_1")
    assert job.status is JobStatus.FAILED
    assert job.failed_stage == "events"


def test_stage_invalid_event_fails_job(tmp_path: Path) -> None:
    harness = _harness__event_extraction(
        tmp_path, [[{"type": "NOPE", "timestamp": 1.0, "description": "x"}], []]
    )
    with pytest.raises(EventExtractionError, match="Invalid extracted event"):
        harness.stage()
    assert harness.ctx.manager.get("job_1").status is JobStatus.FAILED
