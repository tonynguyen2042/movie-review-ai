"""Persistent job lifecycle management (T006).

Every transition is validated by the state machine, persisted through the
T005 repositories, and logged as a structured event (T003).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime

from movie_review.domain import Job, JobStatus
from movie_review.jobs.state_machine import (
    JobNotFoundError,
    transition,
)
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)


class JobManager:
    """Create and advance jobs stored in a SQLite connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, input_file: str) -> Job:
        """Persist a new job in ``CREATED`` with a unique daily-sequenced ID."""
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        job_id = ""
        for seq in range(1, 1000):
            candidate = f"job_{stamp}_{seq:03d}"
            if repo.get_job(self._conn, candidate) is None:
                job_id = candidate
                break
        if not job_id:
            raise RuntimeError(f"Job ID space exhausted for {stamp}")
        job = Job(job_id=job_id, input_file=input_file)
        repo.save_job(self._conn, job)
        with ulog.logging_context(job_id=job_id):
            ulog.log_event(_logger, event="job.created", status="ok")
        return job

    def get(self, job_id: str) -> Job:
        """Load a job or raise :class:`JobNotFoundError`."""
        job = repo.get_job(self._conn, job_id)
        if job is None:
            raise JobNotFoundError(f"Unknown job: {job_id}")
        return job

    def transition(
        self,
        job_id: str,
        to: JobStatus,
        failed_stage: str | None = None,
        error: str | None = None,
    ) -> Job:
        """Validate, persist, and log a state change."""
        current = self.get(job_id)
        job = transition(current, to, failed_stage, error)
        repo.save_job(self._conn, job)
        with ulog.logging_context(job_id=job_id):
            ulog.log_event(
                _logger,
                event="job.transition",
                status="ok",
                from_status=str(current.status),
                to_status=str(to),
            )
        return job

    def fail(self, job_id: str, stage: str, error: str) -> Job:
        """Record a stage failure with its cause."""
        return self.transition(job_id, JobStatus.FAILED, stage, error)
