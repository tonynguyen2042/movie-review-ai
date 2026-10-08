"""The CLI must never look hung while the pipeline runs.

Stages can take many minutes (transcription, TTS, rendering) with no output
of their own, and the whole pipeline is long. Before this, results were
printed only after every stage had finished, so a multi-hour run was
indistinguishable from a freeze: the screen showed the job ID and then
nothing at all.

These tests pin live progress reporting: a line when each stage starts, a
line when it finishes, and a periodic heartbeat so silence is provably
temporary rather than permanent.
"""

from __future__ import annotations

import importlib
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.cli.app import _format_elapsed, _progress_enabled, _ProgressReporter
from movie_review.config.settings import load_settings
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.orchestrator import PipelineContext, StageResult, run_stage

# `import movie_review.cli.app as m` binds the `app` ATTRIBUTE (a Typer
# instance) rather than the module, because cli/__init__.py re-exports it.
# Monkeypatching through that alias would silently set attributes on a Typer
# object and never reach the module under test.
cliapp = importlib.import_module("movie_review.cli.app")


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
def lines() -> list[str]:
    return []


@pytest.fixture
def reporter(lines: list[str], monkeypatch: pytest.MonkeyPatch) -> _ProgressReporter:
    monkeypatch.setattr(cliapp, "_HEARTBEAT_SECONDS", 0.15)
    return _ProgressReporter(echo=lambda msg, **kw: lines.append(msg), enabled=True)


# ---------------------------------------------------------------------------
# The pipeline reports progress as it happens
# ---------------------------------------------------------------------------


def test_stage_start_is_reported_before_the_stage_runs(ctx, lines, reporter) -> None:
    """The start line must arrive while the stage is still working.

    This is the whole point: a line printed only on completion would not tell
    the user anything until the stage was already done.
    """
    seen: list[tuple[str, object]] = []

    def slow_stage(_ctx) -> None:
        # Observed mid-flight, not after the fact.
        assert seen == [("transcript", None)], f"start not reported first: {seen}"
        time.sleep(0.05)

    run_stage("transcript", slow_stage, ctx, on_progress=lambda n, r: seen.append((n, r)))

    assert seen[0] == ("transcript", None)
    assert isinstance(seen[1][1], StageResult)
    assert seen[1][1].success is True


def test_failure_is_reported_live_too(ctx, reporter) -> None:
    """A failing stage must still report its start and its error."""

    def boom(_ctx) -> None:
        raise ValueError("kaboom")

    seen: list[tuple[str, StageResult | None]] = []
    result = run_stage("vision", boom, ctx, on_progress=lambda n, r: seen.append((n, r)))

    assert len(seen) == 2
    assert seen[0] == ("vision", None)
    assert seen[1][1] is not None and seen[1][1].success is False
    assert "kaboom" in result.error


def test_progress_callback_is_optional(ctx) -> None:
    """Existing callers that pass no callback must keep working."""
    result = run_stage("ingest", lambda _c: None, ctx)
    assert result.success is True
    assert result.stage == "ingest"
    assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# A silent stage must still prove it is alive
# ---------------------------------------------------------------------------


def test_heartbeat_fires_while_a_stage_is_running(reporter, lines) -> None:
    """The heartbeat is what distinguishes 'working' from 'hung'."""
    reporter("tts-chunks", None)
    time.sleep(0.5)
    reporter("tts-chunks", StageResult(stage="tts-chunks", success=True, duration_ms=500))
    reporter.close()

    heartbeats = [ln for ln in lines if "still running" in ln]
    assert heartbeats, f"no heartbeat during the stage: {lines}"
    assert all("tts-chunks" in ln for ln in heartbeats)


def test_reporter_orders_lines_start_then_finish(reporter, lines) -> None:
    reporter("scenes", None)
    reporter("scenes", StageResult(stage="scenes", success=True, duration_ms=1))
    reporter.close()

    assert lines[0].strip().startswith("->"), lines
    assert lines[-1].strip().startswith("scenes: OK"), lines


def test_heartbeat_stops_when_the_stage_ends(reporter, lines) -> None:
    """A leaked timer would print a heartbeat after the pipeline finished."""
    reporter("arcs", None)
    reporter("arcs", StageResult(stage="arcs", success=True, duration_ms=1))
    count_at_end = len(lines)
    time.sleep(0.5)
    assert len(lines) == count_at_end, f"heartbeat leaked after completion: {lines}"


def test_heartbeat_cannot_rearm_after_the_stage_ends(monkeypatch, lines) -> None:
    """A heartbeat that fires as the stage finishes must not reschedule itself.

    Without the re-check under the lock, the timer arms after _cancel_timer
    has already run and prints one bogus 'still running' line for a stage that
    finished -- exactly the misleading output this feature exists to remove.
    """
    monkeypatch.setattr(cliapp, "_HEARTBEAT_SECONDS", 0.1)
    live = _ProgressReporter(echo=lambda msg, **kw: lines.append(msg), enabled=True)

    # Simulate the race: a heartbeat captured state, then the stage completed
    # and cancelled the timer, then the heartbeat tries to reschedule.
    live("twists", None)
    live("twists", StageResult(stage="twists", success=True, duration_ms=1))
    lines_before = len(lines)
    live._heartbeat()  # the already-fired heartbeat now tries to rearm
    live.close()

    assert len(lines) == lines_before, f"stale heartbeat printed after end: {lines}"
    time.sleep(0.3)
    assert len(lines) == lines_before, f"stale heartbeat rearmed: {lines}"


def test_close_is_idempotent(reporter) -> None:
    """close() runs from a finally block, possibly after an interrupt."""
    reporter("themes", None)
    reporter.close()
    reporter.close()


def test_heartbeat_thread_does_not_outlive_the_stage(reporter) -> None:
    """No stray timer threads left running after the reporter is done."""
    before = threading.active_count()
    reporter("twists", None)
    reporter("twists", StageResult(stage="twists", success=True, duration_ms=1))
    reporter.close()
    time.sleep(0.4)
    assert threading.active_count() <= before


# ---------------------------------------------------------------------------
# Noise control
# ---------------------------------------------------------------------------


def test_disabled_reporter_is_silent(lines) -> None:
    """Progress must be suppressible for log files and CI."""
    quiet = _ProgressReporter(echo=lambda msg, **kw: lines.append(msg), enabled=False)
    quiet("ingest", None)
    quiet("ingest", StageResult(stage="ingest", success=True, duration_ms=1))
    quiet.close()
    assert lines == []


def test_progress_requires_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """A heartbeat every 10s helps a person and pollutes a redirected log."""
    monkeypatch.setattr(cliapp.sys, "stderr", _FakeStream(tty=False))
    assert _progress_enabled() is False
    monkeypatch.setattr(cliapp.sys, "stderr", _FakeStream(tty=True))
    assert _progress_enabled() is True


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " on "])
def test_progress_env_forces_output_on_a_pipe(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """The desktop app reads the pipe and needs the stage lines.

    T111 spawns the CLI with piped stdio, so the tty test above says "off" for
    exactly the case the GUI depends on. Without this override the app would show
    nothing at all until the pipeline finished.
    """
    monkeypatch.setattr(cliapp.sys, "stderr", _FakeStream(tty=False))
    monkeypatch.setenv("MOVIE_REVIEW_PROGRESS", value)
    assert _progress_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_progress_env_forces_output_off(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """The other direction: a terminal user who wants a quiet run."""
    monkeypatch.setattr(cliapp.sys, "stderr", _FakeStream(tty=True))
    monkeypatch.setenv("MOVIE_REVIEW_PROGRESS", value)
    assert _progress_enabled() is False


def test_progress_env_ignores_an_unrecognised_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo must not silently enable or disable progress.

    Falling back to the tty test is the safe reading: the run behaves exactly as
    it would without the variable, so the mistake is visible rather than hidden.
    """
    monkeypatch.setattr(cliapp.sys, "stderr", _FakeStream(tty=True))
    monkeypatch.setenv("MOVIE_REVIEW_PROGRESS", "maybe")
    assert _progress_enabled() is True
    monkeypatch.setattr(cliapp.sys, "stderr", _FakeStream(tty=False))
    assert _progress_enabled() is False


class _FakeStream:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_progress_goes_to_stderr_not_stdout(capsys, monkeypatch) -> None:
    """stdout stays clean for machine-readable output like the job ID.

    Uses the real typer.echo path -- an injected lambda would make this
    vacuously true by never writing anywhere capsys can see.
    """
    monkeypatch.setattr(cliapp, "_HEARTBEAT_SECONDS", 5)
    live = _ProgressReporter(enabled=True)
    live("ingest", None)
    live("ingest", StageResult(stage="ingest", success=True, duration_ms=1))
    live.close()

    captured = capsys.readouterr()
    assert captured.out == "", f"progress leaked into stdout: {captured.out!r}"
    assert "ingest" in captured.err, f"expected progress on stderr, got {captured.err!r}"


def test_progress_lines_reach_a_real_terminal(capsys, monkeypatch) -> None:
    """End-to-end through the default reporter, not an injected echo."""
    monkeypatch.setattr(cliapp, "_HEARTBEAT_SECONDS", 5)
    live = _ProgressReporter(enabled=True)

    live("transcript", None)
    seen_mid_stage = capsys.readouterr().err
    live("transcript", StageResult(stage="transcript", success=True, duration_ms=1))
    live.close()
    seen_after = capsys.readouterr().err

    assert "-> transcript" in seen_mid_stage, "nothing printed while the stage ran"
    assert "transcript: OK" in seen_after


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0s"), (12, "12s"), (59, "59s"), (60, "1m00s"), (185, "3m05s"), (3600, "60m00s")],
)
def test_elapsed_formatting(seconds: float, expected: str) -> None:
    """Long runs need minute-granularity, not '5400s'."""
    assert _format_elapsed(seconds) == expected


def test_reported_elapsed_reflects_real_duration(reporter, lines) -> None:
    """The number must be measured, not the stage's self-reported figure."""
    reporter("render", None)
    time.sleep(0.3)
    reporter("render", StageResult(stage="render", success=True, duration_ms=999_999))
    reporter.close()

    finish = [ln for ln in lines if ln.strip().startswith("render:")][0]
    assert "999" not in finish, "trusted the stage's duration instead of measuring"
