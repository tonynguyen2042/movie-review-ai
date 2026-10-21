"""Two jobs must never share an id, and one must never overwrite the other.

T128 regression. Job id allocation checked for a free id and then inserted,
which is not atomic. `save_job` used `ON CONFLICT ... DO UPDATE`, so two
concurrent `movie-review process` runs on the same day could pick the same
id -- and the second silently overwrote the first job's `input_file`,
`status` and `created_at`. The first job's artifacts then sat under a job
record pointing at a different movie.

`AGENTS.md` lists "data corruption appears" as a stop condition.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from movie_review.domain import Job
from movie_review.jobs.manager import JobManager
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _db(tmp_path: Path) -> sqlite3.Connection:
    return connect(bootstrap(tmp_path / "jobs.db"))


def test_inserting_the_same_id_twice_reports_the_conflict(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    try:
        job = Job(job_id="job_1", input_file="first.mkv")
        assert repo.insert_job(conn, job) is True
        assert repo.insert_job(conn, job) is False
    finally:
        conn.close()


def test_a_conflicting_insert_leaves_the_first_job_alone(tmp_path: Path) -> None:
    """The second insert must not touch the first job's row."""
    conn = _db(tmp_path)
    try:
        repo.insert_job(conn, Job(job_id="job_1", input_file="first.mkv"))
        repo.insert_job(conn, Job(job_id="job_1", input_file="second.mkv"))

        stored = repo.get_job(conn, "job_1")
        assert stored is not None
        assert stored.input_file == "first.mkv"
    finally:
        conn.close()


def test_the_manager_allocates_distinct_ids(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    try:
        manager = JobManager(conn)
        first = manager.create("first.mkv")
        second = manager.create("second.mkv")
        assert first.job_id != second.job_id
    finally:
        conn.close()


def test_the_manager_does_not_overwrite_an_existing_job(tmp_path: Path) -> None:
    """A taken id must move on to the next one, not replace the row."""
    conn = _db(tmp_path)
    try:
        manager = JobManager(conn)
        # A concurrent run already holds the first id of the day.
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        taken = f"job_{stamp}_001"
        assert repo.insert_job(conn, Job(job_id=taken, input_file="other.mkv")) is True

        created = manager.create("second.mkv")
        assert created.job_id != taken

        stored = repo.get_job(conn, taken)
        assert stored is not None
        assert stored.input_file == "other.mkv", "the other job's row was overwritten"
    finally:
        conn.close()


def test_concurrent_creations_get_distinct_ids(tmp_path: Path) -> None:
    """Two threads creating jobs at once must not collide."""
    db = tmp_path / "jobs.db"
    # Migrate once, up front: two threads migrating the same file at the
    # same time contend for the write lock, which is a different question
    # from the one this test asks.
    connect(bootstrap(db)).close()
    ids: list[str] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def create() -> None:
        # Each thread gets its own connection: sqlite3 objects are not
        # shareable across threads by default.
        conn = connect(bootstrap(db))
        try:
            try:
                # The barrier makes the two threads start together, which is
                # when the race is most likely. It is not required for the
                # assertion: the insert is atomic whatever the interleaving.
                barrier.wait(timeout=30)
            except threading.BrokenBarrierError:
                pass
            manager = JobManager(conn)
            ids.append(manager.create("movie.mkv").job_id)
        except Exception as exc:  # pragma: no cover - the assertion reports it
            errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=create) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors, errors
    assert len(ids) == 2
    assert len(set(ids)) == 2, f"both jobs got the same id: {ids}"
