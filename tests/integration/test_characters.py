"""T027 acceptance: character persistence and schema migration V3."""

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from movie_review.domain import Character, CharacterMention, Job
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect, get_schema_version
from movie_review.storage.schema import MIGRATION_1, MIGRATION_2, SCHEMA_VERSION


@pytest.fixture()
def db(tmp_path: Path) -> Generator[sqlite3.Connection]:
    conn = connect(bootstrap(tmp_path / "c.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    yield conn
    conn.close()


def _character() -> Character:
    return Character(
        id="char_001",
        name="John",
        aliases=["Johnny"],
        first_seen=122.4,
        last_seen=4812.3,
        confidence=0.91,
    )


def test_character_round_trip(db: sqlite3.Connection) -> None:
    repo.save_character(db, "job_1", _character())
    assert repo.get_character(db, "job_1", "char_001") == _character()
    assert repo.get_character(db, "job_1", "missing") is None
    assert [c.id for c in repo.list_characters(db, "job_1")] == ["char_001"]


def test_character_rejects_unknown_job(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_character(db, "missing", _character())


def test_mentions_round_trip(db: sqlite3.Connection) -> None:
    repo.save_mention(
        db,
        "job_1",
        CharacterMention(
            mention="John",
            source_segment_id="seg_1",
            timestamp=10.0,
            character_id="char_001",
        ),
    )
    [mention] = repo.list_mentions(db, "job_1")
    assert mention.mention == "John"
    assert mention.character_id == "char_001"


def test_schema_v3_migrates_from_v2(tmp_path: Path) -> None:
    assert SCHEMA_VERSION == 3
    path = tmp_path / "v2.db"
    with connect(path) as conn:
        for statement in [*MIGRATION_1, *MIGRATION_2]:
            conn.execute(statement)
        conn.execute("PRAGMA user_version = 2")
    with connect(path) as conn:
        from movie_review.storage.database import migrate

        assert migrate(conn) == 3
        assert get_schema_version(conn) == 3
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"characters", "character_mentions"} <= tables
