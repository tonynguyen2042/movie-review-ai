"""Job record (states in :class:`JobStatus`; transitions in T006)."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from movie_review.domain.enums import JobStatus


class Job(BaseModel):
    """One movie-processing job and its lifecycle position."""

    job_id: str = Field(min_length=1)
    input_file: str
    status: JobStatus = JobStatus.CREATED
    failed_stage: str | None = None
    error: str | None = None
    retry_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
