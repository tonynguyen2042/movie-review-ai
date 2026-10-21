"""T039 acceptance: canonical movie-analysis.json assembly."""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import (
    Character,
    Event,
    EventType,
    Evidence,
    EvidenceType,
    Job,
    JobStatus,
    Location,
    Movie,
    MovieMetadata,
    Relationship,
    RelationType,
    Scene,
    SceneAnalysis,
    TranscriptSegment,
)
from movie_review.jobs.manager import JobManager
from movie_review.knowledge.analysis import (
    REQUIRED_KEYS,
    AnalysisError,
    AnalysisResult,
    build_movie_analysis,
)
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


@dataclass
class Harness:
    conn: sqlite3.Connection
    ctx: StageContext

    def build(self) -> AnalysisResult:
        return build_movie_analysis(self.ctx)


def _harness__movie_analysis(tmp_path: Path) -> Harness:
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
        JobStatus.EVENTS_READY,
    ):
        manager.transition("job_1", state)
    repo.save_movie(
        conn,
        "job_1",
        Movie(
            id="movie-job_1",
            metadata=MovieMetadata(
                file="m.mp4",
                sha256="a" * 64,
                duration_seconds=100.0,
                width=640,
                height=480,
                fps=25.0,
                video_codec="h264",
            ),
        ),
    )
    repo.save_scene(
        conn, "job_1", Scene(scene_id="scene_000001", start=0.0, end=10.0, duration=10.0)
    )
    repo.save_transcript_segments(
        conn,
        "job_1",
        [TranscriptSegment(segment_id="seg_1", start=1.0, end=2.0, text="hi")],
    )
    repo.save_character(
        conn, "job_1", Character(id="char_001", name="John", first_seen=0.0, last_seen=50.0)
    )
    repo.save_location(
        conn, "job_1", Location(id="loc_01", name="Dock", first_seen=0.0, last_seen=10.0)
    )
    repo.save_event(
        conn,
        "job_1",
        Event(
            id="event_00001",
            type=EventType.MEETING,
            timestamp=5.0,
            characters=["char_001"],
            description="Meet.",
        ),
    )
    repo.save_relationship(
        conn,
        "job_1",
        Relationship(
            subject="char_001",
            relation=RelationType.PARTICIPATES_IN,
            object="event_00001",
        ),
    )
    repo.save_evidence(
        conn, "job_1", Evidence(id="e1", type=EvidenceType.SCENE, source_id="scene_000001")
    )
    repo.save_speaker_link(conn, "job_1", "SPEAKER_00", "char_001", 0.8)
    jobs_dir = tmp_path / "jobs"
    # The scene analyses now come from the database rather than the artifact, so
    # the fixture seeds a row. The artifact is still written by the vision stage
    # in production; this stage no longer reads it.
    repo.save_scene_analysis(conn, "job_1", SceneAnalysis(scene_id="scene_000001"))
    (jobs_dir / "job_1" / "story").mkdir(parents=True)
    for name, key in (("story-arcs", "arcs"), ("themes", "themes"), ("twists", "twists")):
        (jobs_dir / "job_1" / "story" / f"{name}.json").write_text(
            json.dumps({"items": [], key: []}), encoding="utf-8"
        )
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=jobs_dir,
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )
    return Harness(conn=conn, ctx=ctx)


def test_happy_path(tmp_path: Path) -> None:
    harness = _harness__movie_analysis(tmp_path)
    result = harness.build()
    assert REQUIRED_KEYS <= result.document.keys()
    assert result.document["movie"]["id"] == "movie-job_1"
    assert result.document["timeline"] == [
        {"event_id": "event_00001", "timestamp": 5.0, "type": "MEETING"}
    ]
    assert result.document["speakers"] == [
        {"speaker": "SPEAKER_00", "character_id": "char_001", "confidence": 0.8}
    ]
    assert result.cache_hit is False
    assert result.analysis_path.is_file()
    assert harness.ctx.manager.get("job_1").status is JobStatus.STORY_READY
    assert repo.get_artifact(harness.conn, "job_1-movie-analysis") is not None


def test_scene_carries_its_analysis(tmp_path: Path) -> None:
    harness = _harness__movie_analysis(tmp_path)
    result = harness.build()
    [scene] = result.document["scenes"]
    assert scene["scene_id"] == "scene_000001"
    assert scene["analysis"]["scene_id"] == "scene_000001"


def test_second_run_hits_cache(tmp_path: Path) -> None:
    harness = _harness__movie_analysis(tmp_path)
    harness.build()
    result = harness.build()
    assert result.cache_hit is True


def test_missing_movie_rejected(tmp_path: Path) -> None:
    harness = _harness__movie_analysis(tmp_path)
    with harness.conn:
        harness.conn.execute("DELETE FROM movies WHERE job_id = 'job_1'")
    with pytest.raises(AnalysisError, match="No ingested movie"):
        harness.build()


def test_failed_job_rejected(tmp_path: Path) -> None:
    harness = _harness__movie_analysis(tmp_path)
    harness.ctx.manager.fail("job_1", "events", "earlier")
    with pytest.raises(AnalysisError, match="failed"):
        harness.build()


def test_analysis_is_read_from_the_database_not_the_artifact(tmp_path: Path) -> None:
    """A damaged artifact no longer blocks the story stage.

    The visual analyses are validated when the vision stage writes them, and
    every consumer now queries the table. A truncated vision.json used to stop
    the pipeline here with "Cannot read"; it now costs nothing, because the
    artifact is a copy rather than the source. Artifact integrity is still
    checked by `movie-review validate`.
    """
    harness = _harness__movie_analysis(tmp_path)
    (tmp_path / "jobs" / "job_1" / "vision").mkdir(parents=True, exist_ok=True)
    (tmp_path / "jobs" / "job_1" / "vision" / "vision.json").write_text("nope", encoding="utf-8")

    result = harness.build()

    [scene] = result.document["scenes"]
    assert scene["analysis"]["scene_id"] == "scene_000001"


def test_scene_without_an_analysis_gets_none(tmp_path: Path) -> None:
    """Missing analyses are absent, not fatal: a scene may have none."""
    harness = _harness__movie_analysis(tmp_path)
    with harness.conn:
        harness.conn.execute("DELETE FROM scene_analyses WHERE job_id = 'job_1'")

    result = harness.build()

    assert all(scene["analysis"] is None for scene in result.document["scenes"])
