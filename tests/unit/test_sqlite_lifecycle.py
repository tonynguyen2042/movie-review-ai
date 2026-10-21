"""Database connections must be closed, not merely committed.

T127 regression. `with connect(...)` is a *transaction* context manager: it
commits or rolls back, but it does not close. `bootstrap` used it that way,
so every call leaked an open handle -- and the dashboard calls `bootstrap`
once per request, so the count grew without bound and the database file
stayed locked on Windows.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from movie_review.storage import database
from movie_review.storage.schema import SCHEMA_VERSION


def _record_connections(monkeypatch: pytest.MonkeyPatch) -> list[sqlite3.Connection]:
    """Capture every connection the module opens."""
    created: list[sqlite3.Connection] = []
    real = database.connect

    def recording(path: str | Path) -> sqlite3.Connection:
        conn = real(path)
        created.append(conn)
        return conn

    monkeypatch.setattr(database, "connect", recording)
    return created


def test_bootstrap_closes_the_connection_it_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _record_connections(monkeypatch)
    database.bootstrap(tmp_path / "jobs.db")

    assert created, "bootstrap opened no connection"
    for conn in created:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def test_bootstrap_still_migrates_the_database(tmp_path: Path) -> None:
    """Closing the connection must not lose the migration."""
    db = tmp_path / "jobs.db"
    database.bootstrap(db)
    conn = sqlite3.connect(str(db))
    try:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert version == SCHEMA_VERSION
    assert "jobs" in tables


def test_the_cli_session_closes_its_connection(tmp_path: Path) -> None:
    """A CLI command must not leave the database file locked."""
    from movie_review.cli.app import _session

    db = tmp_path / "jobs.db"
    with _session(str(db)) as (manager, conn):
        assert manager is not None
        assert conn.execute("SELECT 1").fetchone() is not None
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
