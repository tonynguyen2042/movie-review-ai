"""Job record (states in :class:`JobStatus`; transitions in T006)."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from movie_review.domain.enums import JobStatus


class Job(BaseModel):
    """One movie-processing job and its lifecycle position.

    The review options the operator chose at acceptance time live here too.
    They used to reach only a log line: the pipeline read its length and
    style from the configuration instead, so ``--duration 5m --style
    documentary`` produced a 20-minute youtube-style review and reported
    success. The job row is the only record that survives a resume, so it is
    where they belong.
    """

    job_id: str = Field(min_length=1)
    input_file: str
    status: JobStatus = JobStatus.CREATED
    failed_stage: str | None = None
    error: str | None = None
    retry_count: int = Field(default=0, ge=0)
    #: Review style profile name, e.g. "youtube" or "documentary".
    style: str = "youtube"
    #: Spoiler level: "none", "light" or "full".
    spoilers: str = "full"
    #: Target review length in seconds; None means "use the configured default".
    target_seconds: float | None = None
    #: Where the finished output set is written; None means the configured
    #: output directory.
    output_dir: str | None = None
    #: Whether the regenerable intermediates -- the frame images -- are kept.
    #: README section 83 deletes them after a successful analysis.
    keep_intermediates: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
