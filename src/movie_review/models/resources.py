"""Out-of-memory detection and recovery (T071, spec section 67).

On memory pressure: stop the operation, release the model, and retry a
bounded number of times. Workload reduction (fewer frames, smaller batches)
stays with the caller, which knows its own knobs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

_OOM_PATTERNS = (
    "out of memory",
    "memory pressure",
    "cannot allocate memory",
    "mps out of memory",
    "cuda out of memory",
    "cudnn out of memory",
    "allocation failed",
)


class OOMRecoveryError(Exception):
    """OOM recovery itself failed in a classified way."""


def is_oom(error: BaseException) -> bool:
    """True for memory-pressure failures (message match or MemoryError)."""
    if isinstance(error, MemoryError):
        return True
    return any(pattern in str(error).lower() for pattern in _OOM_PATTERNS)


def run_with_oom_recovery(
    operation: Callable[[], Any],
    unload: Callable[[], None],
    *,
    attempts: int = 2,
    stage: str = "stage",
) -> Any:
    """Run once; on OOM release resources and retry (bounded, then raise)."""
    if attempts < 1:
        raise ValueError(f"attempts must be >= 1: {attempts}")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            if not is_oom(exc) or attempt >= attempts:
                raise
            last_error = exc
            with ulog.logging_context(stage=stage):
                ulog.log_event(_logger, event="oom.recovery", status="retrying", attempt=attempt)
            try:
                unload()
            except Exception as unload_exc:
                raise OOMRecoveryError(
                    f"Unload failed during OOM recovery: {unload_exc}"
                ) from unload_exc
    assert last_error is not None
    raise last_error
