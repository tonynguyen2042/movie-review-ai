"""Persistent job lifecycle transitions (T006, README section 8).

The machine is linear along the pipeline with ``FAILED`` reachable from any
state. Resume/retry re-entry belongs to later tasks (T070/T072/T085) and must
extend :data:`TRANSITIONS` explicitly rather than bypassing validation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from movie_review.domain import Job, JobStatus

TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.CREATED: frozenset({JobStatus.INGESTING}),
    JobStatus.INGESTING: frozenset({JobStatus.MEDIA_READY}),
    JobStatus.MEDIA_READY: frozenset({JobStatus.SCENES_READY}),
    JobStatus.SCENES_READY: frozenset({JobStatus.TRANSCRIPT_READY}),
    JobStatus.TRANSCRIPT_READY: frozenset({JobStatus.VISUAL_ANALYSIS_READY}),
    JobStatus.VISUAL_ANALYSIS_READY: frozenset({JobStatus.CHARACTERS_READY}),
    JobStatus.CHARACTERS_READY: frozenset({JobStatus.EVENTS_READY}),
    JobStatus.EVENTS_READY: frozenset({JobStatus.STORY_READY}),
    JobStatus.STORY_READY: frozenset({JobStatus.REVIEW_PLAN_READY}),
    JobStatus.REVIEW_PLAN_READY: frozenset({JobStatus.SCRIPT_READY}),
    JobStatus.SCRIPT_READY: frozenset({JobStatus.SCRIPT_VERIFIED}),
    JobStatus.SCRIPT_VERIFIED: frozenset({JobStatus.AUDIO_READY}),
    JobStatus.AUDIO_READY: frozenset({JobStatus.EDIT_PLAN_READY}),
    JobStatus.EDIT_PLAN_READY: frozenset({JobStatus.RENDERED}),
    JobStatus.RENDERED: frozenset({JobStatus.QUALITY_CHECKED}),
    JobStatus.QUALITY_CHECKED: frozenset({JobStatus.COMPLETED, JobStatus.NEEDS_REVIEW}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.NEEDS_REVIEW: frozenset(),
    JobStatus.FAILED: frozenset(),
}

_TERMINAL = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.NEEDS_REVIEW})


class InvalidTransitionError(ValueError):
    """A requested job state change is not in the lifecycle graph."""


class JobNotFoundError(LookupError):
    """No persisted job exists for the requested ID."""


def allowed(from_status: JobStatus) -> frozenset[JobStatus]:
    """Valid next states: the linear successor plus ``FAILED`` from anywhere."""
    if from_status in _TERMINAL:
        return frozenset()
    return TRANSITIONS[from_status] | frozenset({JobStatus.FAILED})


def transition(
    job: Job,
    to: JobStatus,
    failed_stage: str | None = None,
    error: str | None = None,
) -> Job:
    """Return a copy of ``job`` moved to ``to`` or raise :class:`InvalidTransitionError`.

    Moving to ``FAILED`` requires the failing stage and error description so
    the job retains what/where/why (README section 8).
    """
    if to not in allowed(job.status):
        raise InvalidTransitionError(f"Cannot transition job {job.job_id}: {job.status} -> {to}")
    if to is JobStatus.FAILED and (not failed_stage or not error):
        raise InvalidTransitionError("FAILED transition requires failed_stage and error")
    return job.model_copy(
        update={
            "status": to,
            "failed_stage": failed_stage if to is JobStatus.FAILED else None,
            "error": error if to is JobStatus.FAILED else None,
            "updated_at": datetime.now(UTC),
        }
    )
