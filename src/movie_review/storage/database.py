"""SQLite connection management and schema migration bootstrap (T005)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from movie_review.storage.schema import MIGRATIONS, SCHEMA_VERSION


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with foreign keys and Row access enforced."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Current migration version recorded in the database file."""
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations in order; returns the resulting version.

    Idempotent: re-running on an up-to-date database applies nothing.
    """
    current = get_schema_version(conn)
    if current > SCHEMA_VERSION:
        raise ValueError(f"Database schema v{current} is newer than supported v{SCHEMA_VERSION}")
    for version in range(current + 1, SCHEMA_VERSION + 1):
        with conn:
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version}")
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
