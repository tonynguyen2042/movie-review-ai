"""The reason a failed job stopped has to reach the operator.

T176. Every stage refused a failed job with ``Job <id> failed; resume arrives
in T085``. The job row already held ``failed_stage`` and ``error``, so the run
that died at ``vision`` after two minutes printed a task number instead of the
HTTP failure that caused it, and the operator had to open the database to find
out what happened.
"""

from __future__ import annotations

from movie_review.domain import Job, JobStatus
from movie_review.jobs.failure import job_failure_message


def test_the_message_names_the_failed_stage_and_its_error() -> None:
    job = Job(
        job_id="job_1",
        input_file="m.mp4",
        status=JobStatus.FAILED,
        failed_stage="vision",
        error="cannot reach http://gpu:8000/v1/chat/completions: connection refused",
    )

    message = job_failure_message(job)

    assert "job_1" in message
    assert "'vision'" in message
    assert "connection refused" in message
    assert "T085" not in message


def test_a_job_without_a_recorded_reason_says_so() -> None:
    """FAILED without a stage or an error is the one case the row cannot explain."""
    job = Job(job_id="job_1", input_file="m.mp4", status=JobStatus.FAILED)

    message = job_failure_message(job)

    assert "an unknown stage" in message
    assert "no error was recorded" in message
