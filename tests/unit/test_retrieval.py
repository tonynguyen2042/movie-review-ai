"""T046 acceptance: lexical evidence ranking over persisted knowledge."""

import sqlite3
from pathlib import Path

from movie_review.domain import Character, Event, EventType, Job, TranscriptSegment
from movie_review.review.retrieval import retrieve_evidence
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _db(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(bootstrap(tmp_path / "r.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    repo.save_transcript_segments(
        conn,
        "job_1",
        [
            TranscriptSegment(
                segment_id="seg_1", start=1.0, end=2.0, text="Sarah knew about the murder"
            )
        ],
    )
    repo.save_event(
        conn,
        "job_1",
        Event(
            id="event_00001",
            type=EventType.DISCOVERY,
            timestamp=50.0,
            description="John discovers the hidden photograph.",
        ),
    )
    repo.save_character(
        conn,
        "job_1",
        Character(id="char_001", name="John", aliases=["Johnny"], first_seen=0.0, last_seen=90.0),
    )
    return conn


def test_dialogue_ranked_first(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    [top, *_] = retrieve_evidence("Sarah knew about the murder", conn, "job_1")
    assert top.evidence.source_id == "seg_1"
    assert top.score == 1.0
    conn.close()


def test_event_and_character_hits(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    [top] = retrieve_evidence("hidden photograph", conn, "job_1")
    assert top.evidence.source_id == "event_00001"
    [who] = retrieve_evidence("Johnny", conn, "job_1")
    assert who.evidence.source_id == "char_001"
    conn.close()


def test_no_match_is_empty(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    assert retrieve_evidence("spaceship nebula quantum", conn, "job_1") == []
    assert retrieve_evidence("   ", conn, "job_1") == []
    conn.close()


def test_limit_respected(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    assert len(retrieve_evidence("John Sarah murder", conn, "job_1", limit=1)) == 1
    conn.close()


def test_empty_pool(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "r.db"))
    assert retrieve_evidence("anything here", conn, "job_1") == []
    conn.close()
