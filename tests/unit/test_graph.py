"""T035 acceptance: relationship graph model, builder, and persistence."""

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from movie_review.domain import Event, EventType, Job, Relationship, RelationType, StoryGraph
from movie_review.knowledge.graph import build_graph
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect, get_schema_version, migrate
from movie_review.storage.schema import (
    MIGRATION_1,
    MIGRATION_2,
    MIGRATION_3,
    MIGRATION_4,
    MIGRATION_5,
    MIGRATION_6,
    SCHEMA_VERSION,
)


def test_relation_types_complete() -> None:
    assert len(RelationType) == 15
    for name in ("PARTICIPATES_IN", "LIES_TO", "LOCATED_AT", "PRECEDES", "REVEALS"):
        assert RelationType[name].value == name


def test_relationship_validation() -> None:
    with pytest.raises(ValidationError):
        Relationship(subject="", relation=RelationType.KNOWS, object="char_001")


def _events__graph() -> list[Event]:
    return [
        Event(
            id="event_00002",
            type=EventType.CONFLICT,
            timestamp=20.0,
            characters=["char_001", "char_002"],
            location="loc_01",
            description="Fight.",
            importance=0.9,
        ),
        Event(
            id="event_00001",
            type=EventType.MEETING,
            timestamp=5.0,
            characters=["char_001"],
            description="Meet.",
            importance=0.5,
        ),
    ]


def test_build_graph_edges() -> None:
    graph = build_graph(_events__graph())
    relations = {(e.subject, e.relation, e.object) for e in graph.relationships}
    assert ("char_001", RelationType.PARTICIPATES_IN, "event_00001") in relations
    assert ("char_002", RelationType.PARTICIPATES_IN, "event_00002") in relations
    assert ("event_00002", RelationType.LOCATED_AT, "loc_01") in relations
    assert ("event_00001", RelationType.PRECEDES, "event_00002") in relations
    assert graph.nodes() == ["char_001", "event_00001", "event_00002", "char_002", "loc_01"]
    assert graph.neighbors("event_00002") == ["char_001", "char_002", "loc_01", "event_00001"]
    assert graph.relations_between("event_00001", "event_00002") == [RelationType.PRECEDES]
    assert graph.relations_between("event_00002", "event_00001") == []


def test_graph_round_trip() -> None:
    graph = build_graph(_events__graph())
    assert StoryGraph.model_validate(graph.model_dump()) == graph


def test_persistence_round_trip(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "g.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    graph = build_graph(_events__graph())
    for edge in graph.relationships:
        repo.save_relationship(conn, "job_1", edge)
    stored = repo.list_relationships(conn, "job_1")
    assert len(stored) == len(graph.relationships)
    assert stored[0] == graph.relationships[0]
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_relationship(conn, "missing", graph.relationships[0])
    conn.close()


def test_schema_migrates_from_v6(tmp_path: Path) -> None:
    path = tmp_path / "v6.db"
    with connect(path) as conn:
        for statement in [
            *MIGRATION_1,
            *MIGRATION_2,
            *MIGRATION_3,
            *MIGRATION_4,
            *MIGRATION_5,
            *MIGRATION_6,
        ]:
            conn.execute(statement)
        conn.execute("PRAGMA user_version = 6")
    with connect(path) as conn:
        assert migrate(conn) == SCHEMA_VERSION
        assert get_schema_version(conn) == SCHEMA_VERSION
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "relationships" in tables
