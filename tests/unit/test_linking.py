"""T029 acceptance: co-occurrence linking with honest abstention."""

import sqlite3
from pathlib import Path

import pytest

from movie_review.characters.linking import link_speakers, save_links
from movie_review.domain import DiarizedSegment, Job, SceneAnalysis
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect, get_schema_version, migrate
from movie_review.storage.schema import SCHEMA_VERSION
from tests.helpers import (
    _scene,
)


def test_exclusive_scene_links() -> None:
    scenes = [_scene("scene_000001", 0.0, 10.0)]
    analyses = {"scene_000001": SceneAnalysis(scene_id="scene_000001", characters=["Sarah"])}
    turns = [DiarizedSegment(speaker="SPEAKER_00", start=1.0, end=5.0)]
    [link] = link_speakers(turns, scenes, analyses, {"sarah": "char_001"})
    assert link.character_id == "char_001"
    assert link.confidence > 0.5
    assert any("alone" in reason for reason in link.reasons)


def test_ambiguous_speakers_abstain() -> None:
    scenes = [_scene("scene_000001", 0.0, 10.0)]
    analyses = {
        "scene_000001": SceneAnalysis(scene_id="scene_000001", characters=["Sarah", "John"])
    }
    turns = [
        DiarizedSegment(speaker="SPEAKER_00", start=1.0, end=4.0),
        DiarizedSegment(speaker="SPEAKER_01", start=5.0, end=9.0),
    ]
    ids = {"sarah": "char_001", "john": "char_002"}
    links = link_speakers(turns, scenes, analyses, ids)
    assert all(link.character_id is None for link in links)


def test_unknown_names_ignored() -> None:
    scenes = [_scene("scene_000001", 0.0, 10.0)]
    analyses = {"scene_000001": SceneAnalysis(scene_id="scene_000001", characters=["Zorg"])}
    turns = [DiarizedSegment(speaker="SPEAKER_00", start=1.0, end=5.0)]
    [link] = link_speakers(turns, scenes, analyses, {"sarah": "char_001"})
    assert link.character_id is None


def test_missing_analysis_skipped() -> None:
    scenes = [_scene("scene_000001", 0.0, 10.0)]
    turns = [DiarizedSegment(speaker="SPEAKER_00", start=1.0, end=5.0)]
    [link] = link_speakers(turns, scenes, {}, {"sarah": "char_001"})
    assert link.character_id is None


def test_save_links_round_trip(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "l.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    scenes = [_scene("scene_000001", 0.0, 10.0)]
    analyses = {"scene_000001": SceneAnalysis(scene_id="scene_000001", characters=["Sarah"])}
    turns = [DiarizedSegment(speaker="SPEAKER_00", start=1.0, end=5.0)]
    links = link_speakers(turns, scenes, analyses, {"sarah": "char_001"})
    save_links(conn, "job_1", links)
    assert repo.list_speaker_links(conn, "job_1") == [
        ("SPEAKER_00", "char_001", links[0].confidence)
    ]
    # Upsert overwrites.
    save_links(
        conn,
        "job_1",
        [links[0]],
    )
    assert len(repo.list_speaker_links(conn, "job_1")) == 1
    conn.close()


def test_speaker_link_fk_enforced(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "l.db"))
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_speaker_link(conn, "missing", "SPEAKER_00", None, 0.0)
    conn.close()


def test_schema_migrates_from_v3(tmp_path: Path) -> None:
    from movie_review.storage.schema import MIGRATION_1, MIGRATION_2, MIGRATION_3

    path = tmp_path / "v3.db"
    with connect(path) as conn:
        for statement in [*MIGRATION_1, *MIGRATION_2, *MIGRATION_3]:
            conn.execute(statement)
        conn.execute("PRAGMA user_version = 3")
    with connect(path) as conn:
        assert migrate(conn) == SCHEMA_VERSION
        assert get_schema_version(conn) == SCHEMA_VERSION
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "speakers" in tables
