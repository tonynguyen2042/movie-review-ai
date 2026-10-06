"""Interrupted job recovery: restart-point planning (T072, FR-024).

Maps a persisted job status to the stage that must (re)run next. Failed
jobs retry their recorded stage; completed jobs need nothing; review-gated
jobs wait for a human. Artifact integrity refinement arrives in T073.
"""

from __future__ import annotations

from dataclasses import dataclass

from movie_review.domain import JobStatus
from movie_review.jobs.manager import JobManager
from movie_review.jobs.state_machine import JobNotFoundError


class RecoveryMappingError(Exception):
    """A job status has no resume mapping (an internal gap, not a missing job)."""


_RESUME_STAGE: dict[JobStatus, str] = {
    JobStatus.CREATED: "ingest",
    JobStatus.INGESTING: "ingest",
    JobStatus.MEDIA_READY: "scenes",
    JobStatus.SCENES_READY: "transcript",
    JobStatus.TRANSCRIPT_READY: "vision",
    JobStatus.VISUAL_ANALYSIS_READY: "characters",
    JobStatus.CHARACTERS_READY: "events",
    JobStatus.EVENTS_READY: "story",
    JobStatus.STORY_READY: "review",
    JobStatus.REVIEW_PLAN_READY: "review",
    JobStatus.SCRIPT_READY: "tts",
    JobStatus.SCRIPT_VERIFIED: "tts",
    JobStatus.AUDIO_READY: "render-manifest",
    JobStatus.EDIT_PLAN_READY: "render",
    JobStatus.RENDERED: "quality",
    JobStatus.QUALITY_CHECKED: "done",
    JobStatus.COMPLETED: "done",
    JobStatus.NEEDS_REVIEW: "manual",
}


@dataclass(frozen=True)
class RecoveryPlan:
    """Where a job resumes and why."""

    job_id: str
    status: JobStatus
    resume_stage: str
    reason: str


def recovery_plan(manager: JobManager, job_id: str) -> RecoveryPlan:
    """Determine the restart point for a persisted job."""
    try:
        job = manager.get(job_id)
    except JobNotFoundError as exc:
        raise JobNotFoundError(f"Unknown job: {job_id}") from exc
    if job.status is JobStatus.FAILED:
        stage = job.failed_stage or "unknown"
        return RecoveryPlan(
            job_id=job_id,
            status=job.status,
            resume_stage=stage,
            reason=f"failed in {stage}: {job.error or 'no detail'}",
        )
    resume = _RESUME_STAGE.get(job.status)
    if resume is None:
        # Deliberately not JobNotFoundError: the job exists, the mapping table
        # is incomplete. Conflating the two would make callers report a missing
        # job for what is really an internal gap.
        raise RecoveryMappingError(f"No resume mapping for status {job.status}")
    if resume in ("done", "manual"):
        reason = "already complete" if resume == "done" else "awaiting human review"
    else:
        reason = f"resume with {resume}"
    return RecoveryPlan(job_id=job_id, status=job.status, resume_stage=resume, reason=reason)
