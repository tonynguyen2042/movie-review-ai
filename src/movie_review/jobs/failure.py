"""Why a failed job stopped, in the operator's terms.

Every stage used to refuse a failed job with ``Job <id> failed; resume arrives
in T085`` -- a task number where the reason belongs. The cause was never
missing: the job row keeps ``failed_stage`` and ``error``, and the recovery
plan already reads them. Only the sentence a stage raises was a placeholder,
so a run that failed at ``vision`` after two minutes printed the stage name and
nothing about the HTTP error that killed it.

The stages share the wording here rather than repeating it thirteen times, so
the message cannot drift back into a placeholder one stage at a time.
"""

from __future__ import annotations

from movie_review.domain import Job


def job_failure_message(job: Job) -> str:
    """The reason a stage refuses to run on a job that already failed.

    Names the stage and echoes what it recorded. A job marked FAILED without
    either field is the one case the message cannot explain, so it says so
    instead of inventing a cause.
    """
    stage = job.failed_stage or "an unknown stage"
    reason = job.error or "no error was recorded"
    return f"Job {job.job_id} failed at '{stage}': {reason}. Re-run the pipeline to try again."
