"""The database must be in WAL mode, and the growing tables must be indexed.

T134 regression. The live `data/jobs.db` was verified to be on
`journal_mode=delete` with `synchronous=2` (FULL), and the only indexes were
SQLite's own `sqlite_autoindex_*` — none created by the project.

Every repository write was its own committed transaction, so each one was a
real commit with two fsyncs. `save_mention` runs once per (character,
segment) pair — about 15000 times for a feature film — and the tables that
grow per job had no index, so listing a job's mentions or relationships was
a full table scan.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from movie_review.domain import Job
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _db(tmp_path: Path) -> sqlite3.Connection:
    return connect(bootstrap(tmp_path / "jobs.db"))


def test_the_connection_uses_wal_and_normal_synchrony(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        conn.close()


def test_the_indexes_exist(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    try:
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "idx_mentions_job" in names
        assert "idx_relationships_job" in names
        assert "idx_artifacts_job" in names
    finally:
        conn.close()


def test_listing_a_job_uses_the_index(tmp_path: Path) -> None:
    """A job's mentions must be found by index, not by a full scan."""
    conn = _db(tmp_path)
    try:
        repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM character_mentions WHERE job_id = ?",
            ("job_1",),
        ).fetchall()
        detail = " ".join(str(row[-1]) for row in plan)
        assert "idx_mentions_job" in detail, f"the index was not used: {detail}"
    finally:
        conn.close()


def test_writing_many_mentions_is_one_transaction(tmp_path: Path) -> None:
    """The batch write must be one commit, not one per mention.

    The trace callback reports every row of an ``executemany``, so the
    measure is the number of transactions rather than the number of traced
    statements.
    """
    from movie_review.domain import CharacterMention

    conn = _db(tmp_path)
    try:
        repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
        mentions = [
            CharacterMention(
                mention=f"character {index}",
                source_segment_id=f"seg_{index:05d}",
                timestamp=float(index),
                character_id="char_001",
            )
            for index in range(50)
        ]
        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        repo.save_mentions(conn, "job_1", mentions)
        conn.set_trace_callback(None)

        commits = [s for s in statements if s.strip().upper().startswith("COMMIT")]
        assert len(commits) <= 1, f"the batch issued {len(commits)} commits"
        assert len(repo.list_mentions(conn, "job_1")) == 50
    finally:
        conn.close()


def test_the_batch_writes_still_round_trip(tmp_path: Path) -> None:
    """Batching must not change what is stored."""
    from movie_review.domain import CharacterMention, Event, EventType, SceneAnalysis

    conn = _db(tmp_path)
    try:
        repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))

        mentions = [
            CharacterMention(
                mention="Sarah",
                source_segment_id="seg_00001",
                timestamp=1.0,
                character_id="char_001",
            )
        ]
        repo.save_mentions(conn, "job_1", mentions)
        stored = repo.list_mentions(conn, "job_1")
        assert len(stored) == 1
        assert stored[0].mention == "Sarah"

        events = [
            Event(
                id=f"event_{index:05d}",
                type=EventType.DISCOVERY,
                timestamp=float(index),
                description="Something happens.",
            )
            for index in range(3)
        ]
        repo.save_events(conn, "job_1", events)
        assert len(repo.list_events(conn, "job_1")) == 3

        analyses = [
            SceneAnalysis(
                scene_id=f"scene_{index:06d}",
                location="here",
                characters=[],
                actions=[],
                objects=[],
                emotions=[],
                visual_events=[],
                importance=0.5,
            )
            for index in range(3)
        ]
        repo.save_scene_analyses(conn, "job_1", analyses)
        assert len(repo.list_scene_analyses(conn, "job_1")) == 3
    finally:
        conn.close()
