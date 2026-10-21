"""T027 acceptance: character persistence and schema migration V3."""

import sqlite3
from pathlib import Path

import pytest

from movie_review.domain import CharacterMention, Job
from movie_review.storage import repositories as repo
from movie_review.storage.database import connect, get_schema_version
from movie_review.storage.schema import MIGRATION_1, MIGRATION_2, SCHEMA_VERSION
from tests.helpers import (
    _character,
)


@pytest.fixture()
def seeded_db(db: sqlite3.Connection) -> sqlite3.Connection:
    """The character tests need a job for the characters to hang on."""
    repo.save_job(db, Job(job_id="job_1", input_file="m.mp4"))
    return db


def test_character_round_trip(seeded_db: sqlite3.Connection) -> None:
    repo.save_character(seeded_db, "job_1", _character())
    assert repo.get_character(seeded_db, "job_1", "char_001") == _character()
    assert repo.get_character(seeded_db, "job_1", "missing") is None
    assert [c.id for c in repo.list_characters(seeded_db, "job_1")] == ["char_001"]


def test_character_rejects_unknown_job(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_character(db, "missing", _character())


def test_mentions_round_trip(seeded_db: sqlite3.Connection) -> None:
    repo.save_mention(
        seeded_db,
        "job_1",
        CharacterMention(
            mention="John",
            source_segment_id="seg_1",
            timestamp=10.0,
            character_id="char_001",
        ),
    )
    [mention] = repo.list_mentions(seeded_db, "job_1")
    assert mention.mention == "John"
    assert mention.character_id == "char_001"


def test_schema_migrates_from_v2(tmp_path: Path) -> None:
    path = tmp_path / "v2.db"
    with connect(path) as conn:
        for statement in [*MIGRATION_1, *MIGRATION_2]:
            conn.execute(statement)
        conn.execute("PRAGMA user_version = 2")
    with connect(path) as conn:
        from movie_review.storage.database import migrate

        assert migrate(conn) == SCHEMA_VERSION
        assert get_schema_version(conn) == SCHEMA_VERSION
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"characters", "character_mentions"} <= tables
