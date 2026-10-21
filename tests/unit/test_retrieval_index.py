"""The evidence pool is built once, not once per candidate.

T132 regression. `retrieve_evidence` rebuilt the candidate pool for every
candidate, and each dialogue candidate re-read the entire transcript and then
scanned it for its own segment. The statement count was therefore
`3 + n_segments + n_events + n_characters` for a single retrieval, and the
fact checker ran one retrieval per claim.

Measured on the old code: 100 segments 0.037 s / 463 statements, 400
segments 0.514 s / 763 statements, 800 segments 2.835 s / 1163 statements. At
2500 segments one retrieval cost about 28 seconds, and a script with sixty
claims cost sixty times that.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from movie_review.domain import (
    Claim,
    ClaimType,
    Event,
    EventType,
    Job,
    TranscriptSegment,
)
from movie_review.review.factcheck import check_claims
from movie_review.review.retrieval import build_index, retrieve_evidence
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _db(tmp_path: Path, segments: int) -> sqlite3.Connection:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    repo.save_transcript_segments(
        conn,
        "job_1",
        [
            TranscriptSegment(
                segment_id=f"seg_{index:05d}",
                start=float(index),
                end=float(index) + 1.0,
                text=f"Line {index} about the photograph and the drawer.",
            )
            for index in range(segments)
        ],
    )
    repo.save_event(
        conn,
        "job_1",
        Event(
            id="event_00001",
            type=EventType.DISCOVERY,
            timestamp=10.0,
            description="Someone finds the photograph.",
        ),
    )
    return conn


def _count_statements(conn: sqlite3.Connection) -> list[str]:
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    return statements


def test_the_statement_count_does_not_grow_with_the_transcript(tmp_path: Path) -> None:
    """One retrieval must not issue one query per segment."""
    counts: list[int] = []
    for segments in (100, 400):
        conn = _db(tmp_path / str(segments), segments)
        try:
            statements = _count_statements(conn)
            retrieve_evidence("photograph drawer", conn, "job_1")
            counts.append(len(statements))
        finally:
            conn.set_trace_callback(None)
            conn.close()

    assert counts[0] <= 10, f"too many statements for 100 segments: {counts[0]}"
    # The second pool is four times bigger, but the statement count must not
    # grow with it.
    assert counts[1] <= counts[0] + 2, f"statement count grew with the transcript: {counts}"


def test_retrieval_over_a_long_transcript_is_fast(tmp_path: Path) -> None:
    """800 segments used to take nearly three seconds."""
    conn = _db(tmp_path, 800)
    try:
        started = time.perf_counter()
        results = retrieve_evidence("photograph drawer", conn, "job_1")
        elapsed = time.perf_counter() - started
        assert results, "the retrieval found nothing"
        assert elapsed < 0.5, f"retrieval took {elapsed:.3f}s"
    finally:
        conn.close()


def test_checking_many_claims_reads_the_transcript_once(tmp_path: Path) -> None:
    """The fact checker must not re-read the transcript per claim."""
    conn = _db(tmp_path, 200)
    try:
        claims = [
            Claim(
                claim_id=f"claim_{index:03d}",
                text="The photograph was in the drawer.",
                type=ClaimType.PLOT_FACT,
                evidence=["event_00001"],
            )
            for index in range(20)
        ]
        statements = _count_statements(conn)
        verdicts = check_claims(claims, conn, "job_1")
        count = len(statements)
        assert len(verdicts) == 20
        # A pool build is three queries; the old code ran one transcript read
        # per dialogue candidate per claim.
        assert count <= 10, f"checking 20 claims issued {count} statements"
    finally:
        conn.set_trace_callback(None)
        conn.close()


def test_the_index_answers_the_same_questions(tmp_path: Path) -> None:
    """Building the pool must not change what the retrieval returns."""
    conn = _db(tmp_path, 50)
    try:
        without = retrieve_evidence("photograph drawer", conn, "job_1")
        index = build_index(conn, "job_1")
        with_index = retrieve_evidence("photograph drawer", conn, "job_1", index=index)
        assert [e.evidence.id for e in without] == [e.evidence.id for e in with_index]
        assert [e.score for e in without] == [e.score for e in with_index]
    finally:
        conn.close()
