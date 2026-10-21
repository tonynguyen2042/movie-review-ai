"""T030 acceptance: location canonicalization and persistence."""

import sqlite3
from pathlib import Path

import pytest

from movie_review.domain import Job, Location, SceneAnalysis
from movie_review.knowledge.locations import extract_locations, scene_locations
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect, get_schema_version, migrate
from movie_review.storage.schema import (
    MIGRATION_1,
    MIGRATION_2,
    MIGRATION_3,
    MIGRATION_4,
    SCHEMA_VERSION,
)


def _analysis__locations(scene_id: str, location: str) -> SceneAnalysis:
    return SceneAnalysis(scene_id=scene_id, location=location)


def test_merges_case_variants() -> None:
    analyses = [
        _analysis__locations("scene_000001", "Abandoned Warehouse"),
        _analysis__locations("scene_000002", "abandoned warehouse "),
        _analysis__locations("scene_000003", "ABANDONED WAREHOUSE"),
    ]
    spans = {
        "scene_000001": (0.0, 10.0),
        "scene_000002": (10.0, 20.0),
        "scene_000003": (20.0, 30.0),
    }
    [location] = extract_locations(analyses, spans)
    assert location.id == "loc_001"
    assert (location.first_seen, location.last_seen) == (0.0, 30.0)


def test_skips_empty_and_unknown_scenes() -> None:
    analyses = [
        _analysis__locations("scene_000001", ""),
        _analysis__locations("scene_000002", "   "),
        _analysis__locations("scene_999999", "Nowhere"),
        _analysis__locations("scene_000003", "Dock"),
    ]
    spans = {"scene_000001": (0.0, 1.0), "scene_000002": (1.0, 2.0), "scene_000003": (2.0, 3.0)}
    [location] = extract_locations(analyses, spans)
    assert location.name == "Dock"


def test_ordered_by_first_seen() -> None:
    analyses = [_analysis__locations("b", "Beta"), _analysis__locations("a", "Alpha")]
    spans = {"a": (5.0, 6.0), "b": (0.0, 1.0)}
    locations = extract_locations(analyses, spans)
    assert [(loc.id, loc.name) for loc in locations] == [
        ("loc_001", "Beta"),
        ("loc_002", "Alpha"),
    ]


def test_location_model() -> None:
    location = Location(id="loc_001", name="Dock", first_seen=1.0, last_seen=2.0)
    assert location.confidence == 1.0
    assert Location.model_validate(location.model_dump()) == location


def test_persistence_round_trip(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "l.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    location = Location(id="loc_001", name="Dock", first_seen=1.0, last_seen=2.0)
    repo.save_location(conn, "job_1", location)
    assert repo.list_locations(conn, "job_1") == [location]
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_location(conn, "missing", location)
    conn.close()


def test_scene_locations_helper() -> None:
    from movie_review.domain import Scene

    scenes = [Scene(scene_id="s1", start=1.0, end=2.0, duration=1.0)]
    assert scene_locations(scenes) == {"s1": (1.0, 2.0)}


def test_schema_migrates_from_v4(tmp_path: Path) -> None:
    path = tmp_path / "v4.db"
    with connect(path) as conn:
        for statement in [*MIGRATION_1, *MIGRATION_2, *MIGRATION_3, *MIGRATION_4]:
            conn.execute(statement)
        conn.execute("PRAGMA user_version = 4")
    with connect(path) as conn:
        assert migrate(conn) == SCHEMA_VERSION
        assert get_schema_version(conn) == SCHEMA_VERSION
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "locations" in tables
