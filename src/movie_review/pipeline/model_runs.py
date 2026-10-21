"""Record what every model invocation cost.

README section 53: every model invocation shall record the model, the
runtime, the stage, the prompt's hash, the input and output tokens, the
duration and the temperature, and this is "essential for reproducibility".
Without it there is no way to answer "what produced this?" about a job that
has already finished.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from movie_review.domain import ModelRun, ModelUsage
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)


def _usage_of(adapter: Any) -> ModelUsage | None:
    """The usage the adapter reports for the call it just made."""
    getter = getattr(adapter, "last_usage", None)
    if not callable(getter):
        return None
    try:
        usage = getter()
    except Exception:  # pragma: no cover - a usage reader must never break a run
        return None
    return usage if isinstance(usage, ModelUsage) else None


def _runtime_of(adapter: Any) -> str:
    """The runtime serving the model."""
    runtime = getattr(adapter, "runtime", None)
    if isinstance(runtime, str) and runtime:
        return runtime
    return type(adapter).__name__


@contextmanager
def record_model_run(
    conn: Any,
    job_id: str,
    stage: str,
    adapter: Any,
    model: str,
    *,
    prompt_hash: str = "",
    prompt_version: str | None = None,
    temperature: float | None = None,
) -> Iterator[None]:
    """Record one model invocation, whatever happens to it.

    A call that fails is recorded too: a run that died halfway through the
    vision stage is exactly the case where the record matters.
    """
    started = time.perf_counter()
    try:
        yield
    finally:
        usage = _usage_of(adapter)
        run = ModelRun(
            run_id=f"{stage}-{uuid.uuid4().hex[:12]}",
            job_id=job_id,
            stage=stage,
            model=model,
            runtime=_runtime_of(adapter),
            prompt_hash=prompt_hash,
            prompt_version=prompt_version,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            duration_ms=int((time.perf_counter() - started) * 1000),
            temperature=temperature,
        )
        try:
            repo.save_model_run(conn, job_id, run)
        except Exception as exc:  # pragma: no cover - the record must not break a run
            with ulog.logging_context(job_id=job_id, stage=stage):
                ulog.log_event(
                    _logger,
                    event="model_run.record_failed",
                    status="error",
                    error=str(exc),
                )
