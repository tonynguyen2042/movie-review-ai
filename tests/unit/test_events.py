"""T031 acceptance: event contract and repository."""

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from movie_review.domain import Event, EventType, Job
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect, get_schema_version, migrate
from movie_review.storage.schema import (
    MIGRATION_1,
    MIGRATION_2,
    MIGRATION_3,
    MIGRATION_4,
    MIGRATION_5,
    SCHEMA_VERSION,
)


def _event() -> Event:
    return Event(
        id="event_00031",
        type=EventType.DISCOVERY,
        timestamp=1523.8,
        characters=["char_001"],
        location="loc_04",
        description="John discovers the hidden photograph.",
        importance=0.91,
        evidence=["scene_010"],
    )


def test_event_types_complete() -> None:
    assert len(EventType) == 20
    for name in ("DISCOVERY", "DEATH", "CLIMAX", "RESOLUTION", "OTHER", "FLASH_FORWARD"):
        assert EventType[name].value == name


def test_event_validation() -> None:
    assert Event.model_validate(_event().model_dump()) == _event()
    with pytest.raises(ValidationError):
        Event(id="e", type="NAP", timestamp=1.0, description="x")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Event(id="e", type=EventType.ACTION, timestamp=1.0, description="")
    with pytest.raises(ValidationError):
        Event(id="e", type=EventType.ACTION, timestamp=1.0, description="x", importance=2.0)


def test_event_round_trip(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "e.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    repo.save_event(conn, "job_1", _event())
    assert repo.get_event(conn, "job_1", "event_00031") == _event()
    assert repo.get_event(conn, "job_1", "missing") is None
    earlier = Event(
        id="event_00001",
        type=EventType.INTRODUCTION,
        timestamp=10.0,
        description="Opening.",
    )
    repo.save_event(conn, "job_1", earlier)
    assert [e.id for e in repo.list_events(conn, "job_1")] == ["event_00001", "event_00031"]
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_event(conn, "missing", _event())
    conn.close()


def test_schema_migrates_from_v5(tmp_path: Path) -> None:
    path = tmp_path / "v5.db"
    with connect(path) as conn:
        for statement in [*MIGRATION_1, *MIGRATION_2, *MIGRATION_3, *MIGRATION_4, *MIGRATION_5]:
            conn.execute(statement)
        conn.execute("PRAGMA user_version = 5")
    with connect(path) as conn:
        assert migrate(conn) == SCHEMA_VERSION
        assert get_schema_version(conn) == SCHEMA_VERSION
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "events" in tables
