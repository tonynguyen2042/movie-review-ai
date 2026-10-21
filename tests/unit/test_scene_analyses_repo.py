"""Scene analyses belong in the database, not only in an artifact (T106).

Five stages needed the visual analyses: characters, locations, events,
render-manifest and story. Every one of them reopened vision.json, parsed the
same JSON and re-validated the same objects -- and locations and events parsed
the entries raw, without validation at all. There was no table for them: thirteen
tables, none of them scene_analyses.

vision.json stays the artifact of record. This is the queryable copy, and the
reason a job's visual analysis survives a moved or pruned artifact directory.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from movie_review.domain import Job, JobStatus, SceneAnalysis
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect, migrate
from movie_review.storage.schema import SCHEMA_VERSION
from movie_review.vision.port import AnalysisInput, VLMPort


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = connect(bootstrap(tmp_path / "jobs.db"))
    connection.execute("PRAGMA foreign_keys = ON")
    repo.save_job(connection, Job(job_id="job_a", input_file="m.mp4"))
    return connection


def _analysis(scene_id: str = "scene_000001") -> SceneAnalysis:
    return SceneAnalysis(
        scene_id=scene_id,
        location="Fury cargo hold",
        characters=["a man in a suit"],
        actions=["paces"],
        objects=["flight case"],
        emotions=["tension"],
        visual_events=["power cuts out"],
        importance=0.62,
        confidence=0.74,
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_schema_version_is_bumped() -> None:
    assert SCHEMA_VERSION == 11


def test_migration_creates_the_table_on_an_older_database(tmp_path: Path) -> None:
    """An existing jobs.db must gain the table, not be recreated."""
    connection = connect(bootstrap(tmp_path / "jobs.db"))
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(scene_analyses)")}
    assert "characters_json" in columns
    assert "importance" in columns


def test_migration_is_idempotent(tmp_path: Path) -> None:
    """Re-running migrate must not fail on an existing table."""
    connection = connect(bootstrap(tmp_path / "again.db"))
    migrate(connection)
    migrate(connection)

    columns = {row["name"] for row in connection.execute("PRAGMA table_info(scene_analyses)")}
    assert "confidence" in columns


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_analysis_round_trips_exactly(conn: sqlite3.Connection) -> None:
    """Every field survives, including the five lists."""
    original = _analysis()
    repo.save_scene_analysis(conn, "job_a", original)

    [loaded] = repo.list_scene_analyses(conn, "job_a")

    assert loaded == original


def test_empty_analysis_round_trips(conn: sqlite3.Connection) -> None:
    """A scene with nothing observed is valid and must not become nulls."""
    repo.save_scene_analysis(conn, "job_a", SceneAnalysis(scene_id="scene_000002"))

    [loaded] = repo.list_scene_analyses(conn, "job_a")
    assert loaded.location == ""
    assert loaded.characters == []
    assert loaded.actions == []
    assert loaded.importance == 0.5
    assert loaded.confidence == 1.0


def test_unicode_survives_the_json_columns(conn: sqlite3.Connection) -> None:
    """Story analysis is multilingual; the JSON columns must not mangle it."""
    repo.save_scene_analysis(
        conn,
        "job_a",
        SceneAnalysis(scene_id="scene_000001", location="Phòng khách", actions=["nói chuyện"]),
    )

    [loaded] = repo.list_scene_analyses(conn, "job_a")
    assert loaded.location == "Phòng khách"
    assert loaded.actions == ["nói chuyện"]


def test_saving_twice_replaces_rather_than_duplicates(conn: sqlite3.Connection) -> None:
    """Re-running the vision stage must not leave two rows per scene."""
    repo.save_scene_analysis(conn, "job_a", _analysis())
    repo.save_scene_analysis(conn, "job_a", _analysis().model_copy(update={"location": "Deck"}))

    analyses = repo.list_scene_analyses(conn, "job_a")
    assert len(analyses) == 1
    assert analyses[0].location == "Deck"


def test_analyses_come_back_in_scene_order(conn: sqlite3.Connection) -> None:
    """Downstream stages see them in the same order as the scene timeline."""
    for scene_id in ("scene_000009", "scene_000001", "scene_000005"):
        repo.save_scene_analysis(conn, "job_a", _analysis(scene_id))

    assert [a.scene_id for a in repo.list_scene_analyses(conn, "job_a")] == [
        "scene_000001",
        "scene_000005",
        "scene_000009",
    ]


def test_analyses_are_scoped_to_their_job(conn: sqlite3.Connection) -> None:
    repo.save_job(conn, Job(job_id="job_b", input_file="other.mp4"))
    repo.save_scene_analysis(conn, "job_a", _analysis("scene_000001"))
    repo.save_scene_analysis(conn, "job_b", _analysis("scene_000001"))

    assert len(repo.list_scene_analyses(conn, "job_a")) == 1
    assert len(repo.list_scene_analyses(conn, "job_b")) == 1
    assert repo.get_scene_analysis(conn, "job_a", "scene_000001") is not None
    assert repo.get_scene_analysis(conn, "job_a", "scene_999999") is None


def test_deleting_a_job_cascades(conn: sqlite3.Connection) -> None:
    repo.save_scene_analysis(conn, "job_a", _analysis())
    with conn:
        conn.execute("DELETE FROM jobs WHERE job_id = 'job_a'")

    assert repo.list_scene_analyses(conn, "job_a") == []


def test_missing_analysis_returns_none_rather_than_raising(conn: sqlite3.Connection) -> None:
    assert repo.get_scene_analysis(conn, "job_a", "scene_000001") is None


def test_empty_job_returns_an_empty_list(conn: sqlite3.Connection) -> None:
    assert repo.list_scene_analyses(conn, "job_a") == []


def test_foreign_key_rejects_an_unknown_job(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_scene_analysis(conn, "job_missing", _analysis())


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_a_damaged_json_column_does_not_lose_the_analysis(conn: sqlite3.Connection) -> None:
    """One unreadable list must not cost the whole analysis.

    The alternative -- failing the stage -- would discard location, emotions and
    both scores over a column that is one of six.
    """
    repo.save_scene_analysis(conn, "job_a", _analysis())
    with conn:
        conn.execute(
            "UPDATE scene_analyses SET actions_json = ? WHERE job_id = 'job_a'",
            ("{not json",),
        )

    [loaded] = repo.list_scene_analyses(conn, "job_a")

    assert loaded.actions == []
    assert loaded.location == "Fury cargo hold"
    assert loaded.characters == ["a man in a suit"]
    assert loaded.importance == 0.62


def test_a_json_column_that_is_not_a_list_is_ignored(conn: sqlite3.Connection) -> None:
    repo.save_scene_analysis(conn, "job_a", _analysis())
    with conn:
        conn.execute(
            "UPDATE scene_analyses SET objects_json = ? WHERE job_id = 'job_a'",
            ('{"not": "a list"}',),
        )

    [loaded] = repo.list_scene_analyses(conn, "job_a")

    assert loaded.objects == []


def test_non_string_list_items_are_coerced(conn: sqlite3.Connection) -> None:
    """A number in a text column is a data problem, not a reason to fail."""
    repo.save_scene_analysis(conn, "job_a", _analysis())
    with conn:
        conn.execute(
            "UPDATE scene_analyses SET emotions_json = ? WHERE job_id = 'job_a'",
            ('["focus", 7]',),
        )

    [loaded] = repo.list_scene_analyses(conn, "job_a")

    assert loaded.emotions == ["focus", "7"]


# ---------------------------------------------------------------------------
# The vision stage is what fills the table
# ---------------------------------------------------------------------------


class _FakeVLM(VLMPort):
    """Returns a fixed analysis, so the stage can be run without a model."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def model(self) -> str:
        return "fake-vlm"

    def analyze(self, analysis_input: AnalysisInput, prompt: str) -> SceneAnalysis:
        self.calls.append(analysis_input.scene_id)
        return _analysis(analysis_input.scene_id)

    def unload(self) -> None:
        return None


def test_run_visual_analysis_persists_each_scene(tmp_path: Path) -> None:
    """Called directly: the orchestrator wrapper would only hide this.

    Going through the orchestrator would mean stubbing the very function under
    test, which proves nothing about whether it writes the rows.
    """
    from movie_review.cache.manager import CacheManager
    from movie_review.config.settings import load_settings
    from movie_review.domain import Scene, TranscriptSegment
    from movie_review.jobs.manager import JobManager
    from movie_review.pipeline.context import StageContext
    from movie_review.vision.analysis import run_visual_analysis

    connection = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(connection)
    repo.save_job(connection, Job(job_id="job_v", input_file="m.mp4"))
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
    ):
        manager.transition("job_v", state)

    scenes = [
        Scene(scene_id="scene_000001", start=0.0, end=5.0, duration=5.0),
        Scene(scene_id="scene_000002", start=5.0, end=12.0, duration=7.0),
    ]
    for scene in scenes:
        repo.save_scene(connection, "job_v", scene)
    repo.save_transcript_segments(
        connection,
        "job_v",
        [TranscriptSegment(segment_id="s1", start=0.0, end=1.0, text="hi")],
    )

    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    frames = {scene.scene_id: [frame] for scene in scenes}

    ctx = StageContext(
        job_id="job_v",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=connection,
    )

    result = run_visual_analysis(
        scenes,
        frames,
        repo.list_transcript_segments(connection, "job_v"),
        ctx,
        port=_FakeVLM(),
    )

    assert len(result.analyses) == 2
    stored = repo.list_scene_analyses(connection, "job_v")
    assert [a.scene_id for a in stored] == ["scene_000001", "scene_000002"]
    assert stored[0].location == "Fury cargo hold"
    assert stored[0].confidence == pytest.approx(0.74)


def test_a_partial_run_leaves_no_orphan_rows(tmp_path: Path) -> None:
    """A failed analysis must not leave rows the story stage would read.

    Rows are written after the whole analysis loop, so a stage that dies on
    scene 40 writes nothing and the story stage sees the job as it was.
    """
    from movie_review.cache.manager import CacheManager
    from movie_review.config.settings import load_settings
    from movie_review.domain import Scene
    from movie_review.jobs.manager import JobManager
    from movie_review.pipeline.context import StageContext
    from movie_review.vision.analysis import VisualAnalysisError, run_visual_analysis

    connection = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(connection)
    repo.save_job(connection, Job(job_id="job_v", input_file="m.mp4"))
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
    ):
        manager.transition("job_v", state)

    scene = Scene(scene_id="scene_000001", start=0.0, end=5.0, duration=5.0)
    repo.save_scene(connection, "job_v", scene)
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")

    ctx = StageContext(
        job_id="job_v",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=connection,
    )

    class _Failing(VLMPort):
        @property
        def model(self) -> str:
            return "fake-vlm"

        def analyze(self, analysis_input: AnalysisInput, prompt: str) -> SceneAnalysis:
            raise RuntimeError("HTTP 500")

        def unload(self) -> None:
            return None

    with pytest.raises(VisualAnalysisError):
        run_visual_analysis([scene], {scene.scene_id: [frame]}, [], ctx, port=_Failing())

    assert repo.list_scene_analyses(connection, "job_v") == []
