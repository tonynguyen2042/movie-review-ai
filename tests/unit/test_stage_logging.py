"""Stage logs must actually reach the terminal (T099).

A silent run is indistinguishable from a hung one. The CLI heartbeat proves the
process is alive, but it cannot say *why* a stage is slow or *why* one failed --
only the stage's own log lines do that.

The orchestrator used ``logging.getLogger(f"pipeline.{stage}")``, which builds a
logger at the root of the tree rather than under ``movie_review``. Logging is
configured in exactly one place (``configure_logging``), and it attaches a
handler to the ``movie_review`` logger with ``propagate = False``. A root-level
sibling therefore had no handler, and its INFO records were discarded by the
root logger's default WARNING level.

These tests pin the observable behaviour -- records arrive on the stream that
``configure_logging`` chose -- rather than asserting on logger names, which is
how the bug survived a green suite in the first place.
"""

from __future__ import annotations

import io
import json
import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.pipeline.orchestrator import PipelineContext, run_stage
from movie_review.utils import logging as ulog


@pytest.fixture
def ctx() -> PipelineContext:
    """A context with real collaborators but no side effects on disk."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return PipelineContext(
        job_id="job_test",
        movie_path=Path("movie.mp4"),
        jobs_dir=Path("."),
        cache=CacheManager(Path(".")),
        manager=JobManager(conn),
        settings=load_settings(),
        conn=conn,
    )


@pytest.fixture
def captured_logs() -> Iterator[io.StringIO]:
    """Collect every JSON log line the package emits, then restore logging."""
    previous_handlers = list(logging.getLogger("movie_review").handlers)
    previous_level = logging.getLogger("movie_review").level
    buffer = io.StringIO()
    yield buffer
    logger = logging.getLogger("movie_review")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    for handler in previous_handlers:
        logger.addHandler(handler)
    logger.setLevel(previous_level)


def _events(buffer: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# A completed stage announces itself
# ---------------------------------------------------------------------------


def test_stage_completion_is_logged(captured_logs: io.StringIO, ctx: PipelineContext) -> None:
    """The user must be able to see that a stage finished, and how long it took."""
    ulog.configure_logging("INFO", stream=captured_logs)

    run_stage("scenes", lambda _c: None, ctx)

    events = _events(captured_logs)
    assert [e["event"] for e in events] == ["stage.completed"], events
    assert events[0]["stage"] == "scenes"
    assert events[0]["status"] == "ok"
    assert events[0]["job_id"] == "job_test"
    assert events[0]["duration_ms"] >= 0


def test_stage_failure_is_logged_with_the_error(
    captured_logs: io.StringIO, ctx: PipelineContext
) -> None:
    """The reason a stage failed must be in the log, not only in the exit code.

    A failed stage without its error logged is the worst case: the user sees
    the run stop and has nothing to act on.
    """

    def boom(_c: PipelineContext) -> None:
        raise RuntimeError("ffmpeg exited 1")

    ulog.configure_logging("INFO", stream=captured_logs)

    result = run_stage("render", boom, ctx)

    assert result.success is False
    events = _events(captured_logs)
    assert [e["event"] for e in events] == ["stage.failed"], events
    assert events[0]["status"] == "error"
    assert "ffmpeg exited 1" in events[0]["error"]
    assert events[0]["stage"] == "render"


# ---------------------------------------------------------------------------
# Every stage gets its own logger, and all of them reach the same stream
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stage",
    [
        "ingest",
        "scenes",
        "transcript",
        "vision",
        "characters",
        "locations",
        "events",
        "arcs",
        "themes",
        "twists",
        "story",
        "review",
        "tts-chunks",
        "tts-concat",
        "tts-reconcile",
        "render-manifest",
        "render",
        "quality",
    ],
)
def test_every_stage_in_the_sequence_logs(
    stage: str, captured_logs: io.StringIO, ctx: PipelineContext
) -> None:
    """The bug was namespace-wide, so pin the whole sequence, not one stage.

    'quality' is last on purpose: a fix that only repaired the early stages
    would leave the long ones at the end of the pipeline silent.
    """
    ulog.configure_logging("INFO", stream=captured_logs)

    run_stage(stage, lambda _c: None, ctx)

    events = _events(captured_logs)
    assert len(events) == 1, f"{stage} produced no log line: {events}"
    assert events[0]["stage"] == stage


def test_stage_logs_carry_job_and_stage_context(captured_logs: io.StringIO) -> None:
    """NFR-002 fields must be present, or the lines cannot be correlated."""
    ulog.configure_logging("INFO", stream=captured_logs)

    with ulog.logging_context(job_id="job_ctx", stage="tts-chunks"):
        ulog.get_logger("pipeline.tts-chunks").info("probe")

    payload = _events(captured_logs)[0]
    assert payload["job_id"] == "job_ctx"
    assert payload["stage"] == "tts-chunks"


# ---------------------------------------------------------------------------
# The fix must not simply reconfigure logging globally
# ---------------------------------------------------------------------------


def test_stage_logger_does_not_mutate_global_logging(
    captured_logs: io.StringIO, ctx: PipelineContext
) -> None:
    """Resolving a logger may not attach handlers or change levels.

    configure_logging is the single owner of handler wiring. A stage that
    installed its own StreamHandler would send output somewhere the user is
    not watching -- the original bug in a different shape.
    """
    ulog.configure_logging("INFO", stream=captured_logs)
    before = list(logging.getLogger("movie_review").handlers)
    before_root = list(logging.getLogger().handlers)
    before_level = logging.getLogger().level

    run_stage("arcs", lambda _c: None, ctx)

    assert list(logging.getLogger("movie_review").handlers) == before
    assert logging.getLogger().level == before_level
    # Compared rather than asserted empty: pytest's own logging plugin installs
    # capture handlers on the root logger, so "root has no handlers" is not a
    # property this test can make. What matters is that nothing was added here.
    assert list(logging.getLogger().handlers) == before_root, "root logger was modified"


def test_stage_logger_is_a_movie_review_child(captured_logs: io.StringIO) -> None:
    """Guard the namespace directly: it is the actual defect.

    The behavioural tests above pin the symptom; this one fails at the cause,
    so a future refactor cannot reintroduce the bug in a way that happens to
    pass the symptom tests (e.g. by adding a root handler instead).
    """
    ulog.configure_logging("INFO", stream=captured_logs)

    from movie_review.pipeline.orchestrator import _stage_logger

    logger = _stage_logger("review")
    assert logger.name.startswith("movie_review.")
    assert logger.parent is logging.getLogger("movie_review")
    assert logger.getEffectiveLevel() <= logging.INFO, "INFO records would be filtered out"


def test_stage_context_is_unaffected(captured_logs: io.StringIO) -> None:
    """The plain StageContext stays constructible; only the logger changed."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ctx = StageContext(
        job_id="job_plain",
        jobs_dir=Path("."),
        conn=conn,
        manager=JobManager(conn),
        cache=CacheManager(Path(".")),
        settings=load_settings(),
    )
    assert ctx.job_id == "job_plain"
