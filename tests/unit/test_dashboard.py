"""T089 acceptance: job dashboard serves job data."""

import json
import threading
import time
from pathlib import Path

import pytest

from movie_review.ui.dashboard import JobDashboard


def test_dashboard_get_jobs(tmp_path: Path) -> None:
    """Dashboard can fetch jobs from database."""
    db_path = tmp_path / "jobs.db"
    # Create a minimal jobs table
    import sqlite3
    from movie_review.storage.database import bootstrap
    conn = sqlite3.connect(str(bootstrap(db_path)))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            input_file TEXT,
            status TEXT,
            failed_stage TEXT,
            error TEXT,
            retry_count INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        INSERT INTO jobs (job_id, input_file, status, created_at, updated_at)
        VALUES ('job_test', 'movie.mp4', 'COMPLETED', '2024-01-01T00:00:00', '2024-01-01T00:00:00')
    """)
    conn.commit()
    conn.close()
    
    dashboard = JobDashboard(db_path=str(db_path))
    jobs = dashboard.get_jobs()
    
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "job_test"
    assert jobs[0]["status"] == "COMPLETED"


def test_dashboard_get_job_details(tmp_path: Path) -> None:
    """Dashboard can fetch job details with artifacts."""
    db_path = tmp_path / "jobs.db"
    import sqlite3
    from movie_review.storage.database import bootstrap
    conn = sqlite3.connect(str(bootstrap(db_path)))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            input_file TEXT,
            status TEXT,
            failed_stage TEXT,
            error TEXT,
            retry_count INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            job_id TEXT,
            stage TEXT,
            version INTEGER,
            created_at TEXT,
            input_hash TEXT,
            output_hash TEXT,
            model TEXT,
            prompt_version TEXT
        )
    """)
    conn.execute("""
        INSERT INTO jobs (job_id, input_file, status, created_at, updated_at)
        VALUES ('job_test', 'movie.mp4', 'COMPLETED', '2024-01-01T00:00:00', '2024-01-01T00:00:00')
    """)
    conn.execute("""
        INSERT INTO artifacts (artifact_id, job_id, stage, version, created_at, input_hash, output_hash)
        VALUES ('job_test-ingest', 'job_test', 'ingest', 1, '2024-01-01T00:00:00', 'abc', 'def')
    """)
    conn.commit()
    conn.close()
    
    dashboard = JobDashboard(db_path=str(db_path))
    job = dashboard.get_job_details("job_test")
    
    assert job is not None
    assert job["job_id"] == "job_test"
    assert "artifacts" in job
    assert len(job["artifacts"]) == 1


def test_dashboard_start_stop(tmp_path: Path) -> None:
    """Dashboard server can start and stop."""
    db_path = tmp_path / "jobs.db"
    import sqlite3
    from movie_review.storage.database import bootstrap
    conn = sqlite3.connect(str(bootstrap(db_path)))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            input_file TEXT,
            status TEXT,
            failed_stage TEXT,
            error TEXT,
            retry_count INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    
    dashboard = JobDashboard(host="127.0.0.1", port=0, db_path=str(db_path))  # port 0 = auto
    # Get actual port
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    
    # Use a different approach - just test the server starts
    dashboard = JobDashboard(host="127.0.0.1", port=port, db_path=str(db_path))
    dashboard.start()
    time.sleep(0.2)  # Give server time to start
    
    # Test API endpoint
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/jobs") as resp:
            data = json.loads(resp.read().decode())
            assert isinstance(data, list)
    finally:
        dashboard.stop()