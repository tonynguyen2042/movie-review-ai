"""Stage retry with classified errors (T070, spec section 65).

Retries transient failures up to a bounded attempt count, then surfaces the
last error instead of looping forever. Callers narrow ``retry_on`` to
transient failures; everything else propagates immediately.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry configuration."""

    max_attempts: int = 3
    retry_on: tuple[type[Exception], ...] = (Exception,)
    backoff_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1: {self.max_attempts}")
        if self.backoff_seconds < 0:
            raise ValueError(f"backoff must be >= 0: {self.backoff_seconds}")


@dataclass(frozen=True)
class RetryResult:
    """Successful value plus attempts consumed."""

    value: Any
    attempts: int


def run_with_retry(
    operation: Callable[[], Any],
    policy: RetryPolicy | None = None,
    *,
    stage: str = "stage",
    should_retry: Callable[[BaseException], bool] | None = None,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> RetryResult:
    """Run ``operation`` until success or policy exhaustion (then raise).

    ``should_retry`` decides whether a given failure is worth another
    attempt. It defaults to the policy's ``retry_on`` types. A predicate is
    needed where the failure that matters is not the one that was raised --
    a stage wraps its cause, and the cause is what says whether the
    failure was transient.
    """
    active = policy or RetryPolicy()
    last_error: Exception | None = None
    for attempt in range(1, active.max_attempts + 1):
        try:
            return RetryResult(value=operation(), attempts=attempt)
        except Exception as exc:
            retryable = should_retry(exc) if should_retry else isinstance(exc, active.retry_on)
            if not retryable:
                raise
            last_error = exc
            with ulog.logging_context(stage=stage):
                ulog.log_event(
                    _logger,
                    event="retry.attempt",
                    status="failed",
                    attempt=attempt,
                    error=str(exc),
                )
            if on_retry is not None:
                on_retry(attempt, exc)
            if attempt < active.max_attempts and active.backoff_seconds > 0:
                time.sleep(active.backoff_seconds)
    assert last_error is not None
    raise last_error
