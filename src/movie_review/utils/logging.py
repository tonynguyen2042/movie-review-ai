"""Structured JSON logging with job/stage context (T003).

Every log record carries the NFR-002 minimum context (``job_id``, ``stage``,
``event``, ``status``, ``duration_ms``, ``error``) when available. Context is
kept in a :mod:`contextvars` mapping so concurrent jobs do not leak fields
into each other. Standard library only.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TextIO

_LOGGER_NAMESPACE = "movie_review"

_context: ContextVar[dict[str, Any] | None] = ContextVar("movie_review_log_context", default=None)


def current_context() -> dict[str, Any]:
    """The logging context bound for this thread/task (empty when none).

    Stage functions bind ``job_id`` and ``stage`` via :func:`logging_context`;
    callers that live inside that binding but outside the stage -- the model
    ports, which run in its threads -- read the binding through this.
    """
    return dict(_context.get() or {})


def _standard_record_attrs() -> set[str]:
    """Attribute names natively present on every :class:`logging.LogRecord`."""
    record = logging.LogRecord(
        name="probe",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="",
        args=None,
        exc_info=None,
    )
    return set(record.__dict__)


_STANDARD_ATTRS = _standard_record_attrs()


@contextmanager
def logging_context(
    job_id: str | None = None, stage: str | None = None, **extra: Any
) -> Iterator[None]:
    """Bind logging context for the enclosed block; nesting restores outer values."""
    merged = current_context()
    if job_id is not None:
        merged["job_id"] = job_id
    if stage is not None:
        merged["stage"] = stage
    merged.update(extra)
    token = _context.set(merged)
    try:
        yield
    finally:
        _context.reset(token)


class JsonFormatter(logging.Formatter):
    """Render records as single-line JSON documents (NFR-002 fields first)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(current_context())
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key != "message":
                payload.setdefault(key, value)
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def parse_level(level: str) -> int:
    """Map a level name (e.g. ``INFO``) to its numeric value or raise."""
    try:
        return logging.getLevelNamesMapping()[level.upper()]
    except KeyError:
        raise ValueError(f"Unknown log level: {level!r}") from None


def configure_logging(
    level: str = "INFO",
    stream: TextIO | None = None,
    json_output: bool = True,
) -> logging.Handler:
    """Configure the ``movie_review`` logger; replaces its handlers (re-runnable).

    Returns the installed handler so callers/tests can inspect or remove it.
    """
    logger = logging.getLogger(_LOGGER_NAMESPACE)
    logger.setLevel(parse_level(level))
    logger.propagate = False
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
    handler: logging.Handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter() if json_output else logging.Formatter())
    logger.addHandler(handler)
    return handler


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``movie_review`` namespace."""
    return logging.getLogger(f"{_LOGGER_NAMESPACE}.{name}")


def log_event(
    logger: logging.Logger,
    event: str,
    status: str,
    duration_ms: int | None = None,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit one structured pipeline event (plan.md section 9)."""
    extra: dict[str, Any] = {"event": event, "status": status}
    if duration_ms is not None:
        extra["duration_ms"] = duration_ms
    extra.update(fields)
    logger.log(level, event, extra=extra)
