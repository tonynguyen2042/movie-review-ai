"""SQLite connection management and schema migration bootstrap (T005)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from movie_review.storage.schema import MIGRATIONS, SCHEMA_VERSION


def connect(path: str | Path) -> sqlite3.Connection:
    r"""Open a SQLite connection with foreign keys and Row access enforced.

    The journal is in WAL mode and the synchronous level is NORMAL. The
    default -- a rollback journal with FULL synchronisation -- makes every
    commit two fsyncs, and the repository writes one row per commit. The
    database was verified to be on \`journal_mode=delete\` with
    \`synchronous=2\`, so a feature-length run paid thousands of fsyncs.

    WAL is safe against an application crash with NORMAL, and it lets
    readers run while a writer is active, which the dashboard needs.
    """
    # A longer busy timeout: the parallel stages write from more than one
    # thread, and the five-second default is not enough on a loaded machine.
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL is a property of the file, not the connection, so setting it on
    # every connection is cheap and keeps a connection opened directly --
    # rather than through bootstrap -- in the same mode.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Current migration version recorded in the database file."""
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations in order; returns the resulting version.

    Idempotent: re-running on an up-to-date database applies nothing.

    The version check and the migration run under one exclusive lock. Two
    processes that open the same database at the same time both read the old
    version and both try to apply the same migration -- and the second one
    fails with "duplicate column name". A job that started while another was
    starting could not open the database at all.
    """
    current = get_schema_version(conn)
    if current > SCHEMA_VERSION:
        raise ValueError(f"Database schema v{current} is newer than supported v{SCHEMA_VERSION}")
    if current == SCHEMA_VERSION:
        return current

    # Autocommit for the duration, so the exclusive lock is explicit and
    # spans the version check and the writes.
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = get_schema_version(conn)
            for version in range(current + 1, SCHEMA_VERSION + 1):
                for statement in MIGRATIONS[version]:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {version}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.isolation_level = "DEFERRED"
    return get_schema_version(conn)


def bootstrap(path: str | Path) -> Path:
    """Create parent directories and migrate a database file to current schema.

    The connection is closed on the way out. ``with connect(...)`` is a
    *transaction* context manager: it commits or rolls back, but it does not
    close. Every call therefore leaked an open handle, and the dashboard
    calls this once per request, so the count grew without bound and the
    database file stayed locked on Windows.
    """
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(resolved)) as conn:
        migrate(conn)
        conn.commit()
    return resolved
