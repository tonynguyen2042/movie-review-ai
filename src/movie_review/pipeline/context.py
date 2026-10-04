"""Pipeline stage execution context (T011).

Later stages share this context: job identity, persistence, artifact and
cache roots, settings, and logging. No orchestration lives here yet.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import AppSettings
from movie_review.jobs.manager import JobManager


@dataclass
class StageContext:
    """Everything a stage needs beyond its specific inputs."""

    job_id: str
    jobs_dir: Path
    cache: CacheManager
    manager: JobManager
    settings: AppSettings
    conn: sqlite3.Connection

    @classmethod
    def from_settings(
        cls,
        settings: AppSettings,
        conn: sqlite3.Connection,
        job_id: str,
    ) -> StageContext:
        """Build a context with conventional ``data/jobs`` and ``data/cache`` roots."""
        data_dir = Path(settings.paths.data_dir)
        return cls(
            job_id=job_id,
            jobs_dir=data_dir / "jobs",
            cache=CacheManager(data_dir / "cache"),
            manager=JobManager(conn),
            settings=settings,
            conn=conn,
        )
