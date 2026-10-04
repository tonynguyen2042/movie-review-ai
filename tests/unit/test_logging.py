"""T003 acceptance: JSON logging carries job/stage context."""

import io
import json
import logging

import pytest

from movie_review.config.settings import load_settings
from movie_review.utils import logging as ulog


def _capture(logger_name: str) -> tuple[logging.Logger, io.StringIO]:
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(ulog.JsonFormatter())
    logger.addHandler(handler)
    return logger, stream


def _lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_event_carries_job_stage_context() -> None:
    logger, stream = _capture("test.t003.context")
    with ulog.logging_context(job_id="job_1", stage="ingest"):
        ulog.log_event(logger, event="stage.started", status="ok", duration_ms=12)
    (record,) = _lines(stream)
    assert record["job_id"] == "job_1"
    assert record["stage"] == "ingest"
    assert record["event"] == "stage.started"
    assert record["status"] == "ok"
    assert record["duration_ms"] == 12
    assert record["level"] == "INFO"


def test_context_nesting_restores_outer() -> None:
    logger, stream = _capture("test.t003.nesting")
    with ulog.logging_context(job_id="job_1", stage="outer"):
        with ulog.logging_context(stage="inner"):
            logger.info("deep")
        logger.info("shallow")
    deep, shallow = _lines(stream)
    assert deep["stage"] == "inner"
    assert deep["job_id"] == "job_1"
    assert shallow["stage"] == "outer"


def test_context_cleared_after_exit() -> None:
    logger, stream = _capture("test.t003.cleared")
    with ulog.logging_context(job_id="job_1"):
        pass
    logger.info("after")
    (record,) = _lines(stream)
    assert "job_id" not in record


def test_exception_logged_with_error() -> None:
    logger, stream = _capture("test.t003.exc")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.exception("failed")
    (record,) = _lines(stream)
    assert "boom" in str(record["error"])


def test_configure_logging_from_settings() -> None:
    settings = load_settings()
    assert settings.logging.level == "INFO"
    handler = ulog.configure_logging(level=settings.logging.level)
    try:
        logger = logging.getLogger("movie_review")
        assert logger.level == logging.INFO
        assert handler in logger.handlers
        assert isinstance(handler.formatter, ulog.JsonFormatter)
    finally:
        logger.removeHandler(handler)


def test_unknown_level_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown log level"):
        ulog.configure_logging(level="VERBOSE")
