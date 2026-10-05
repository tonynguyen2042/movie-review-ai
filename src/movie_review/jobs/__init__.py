"""Job state machine and lifecycle (T006 machine, T072 recovery)."""

from movie_review.jobs.manager import JobManager
from movie_review.jobs.recovery import RecoveryPlan, recovery_plan
from movie_review.jobs.state_machine import (
    TRANSITIONS,
    InvalidTransitionError,
    JobNotFoundError,
    allowed,
    transition,
)

__all__ = [
    "TRANSITIONS",
    "InvalidTransitionError",
    "JobManager",
    "JobNotFoundError",
    "RecoveryPlan",
    "allowed",
    "recovery_plan",
    "transition",
]
