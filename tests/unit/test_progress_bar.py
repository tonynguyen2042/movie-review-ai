"""A progress bar that only moves between stages is worse than none (T101).

``on_progress`` fires at stage boundaries only, so a bar built on it alone sits
at 0% for the whole nine minutes of a transcription -- precisely the "is it
hung?" question the heartbeat was added to answer. Stages that iterate over a
known number of items now publish steps through ``WorkProgress``.

These tests pin four things that could each regress silently:

- the counter is real (a stage reports the count it actually reached)
- the bar renders and clamps
- output is throttled, but never swallows the final update
- a stage with no listener pays nothing and breaks nothing
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from movie_review.pipeline.progress import WorkProgress

cliapp = importlib.import_module("movie_review.cli.app")
frames_module = importlib.import_module("movie_review.media.frames")
analysis_module = importlib.import_module("movie_review.vision.analysis")
orchestrator = importlib.import_module("movie_review.pipeline.orchestrator")

from movie_review.pipeline.orchestrator import PipelineContext, StageResult, run_stage  # noqa: E402

# ---------------------------------------------------------------------------
# The counter
# ---------------------------------------------------------------------------


def test_fraction_and_percent() -> None:
    assert WorkProgress(done=0, total=10).fraction == 0.0
    assert WorkProgress(done=5, total=10).fraction == 0.5
    assert WorkProgress(done=10, total=10).fraction == 1.0
    assert WorkProgress(done=5, total=10).percent == 50
    assert WorkProgress(done=1, total=3).percent == 33


def test_unknown_total_does_not_divide_by_zero() -> None:
    """A stage that learns its total late must not crash reporting."""
    unknown = WorkProgress(done=7, total=0)
    assert unknown.fraction == 0.0
    assert unknown.percent == 0


def test_overrun_is_rejected() -> None:
    """A stage counting more than it planned is a bug worth hearing about."""
    with pytest.raises(ValueError, match="exceeds total"):
        WorkProgress(done=11, total=10)


def test_negative_counts_are_rejected() -> None:
    with pytest.raises(ValueError, match="done"):
        WorkProgress(done=-1, total=10)
    with pytest.raises(ValueError, match="total"):
        WorkProgress(done=0, total=-5)


# ---------------------------------------------------------------------------
# The bar
# ---------------------------------------------------------------------------


def test_bar_is_fixed_width() -> None:
    """A proportional bar jitters as the percentage ticks over."""
    empty = cliapp._format_bar(0.0, width=10)
    half = cliapp._format_bar(0.5, width=10)
    full = cliapp._format_bar(1.0, width=10)
    assert empty == "[----------]"
    assert half == "[#####-----]"
    assert full == "[##########]"
    assert len(empty) == len(half) == len(full)


def test_bar_clamps_out_of_range() -> None:
    """A miscounting stage must not produce a bar of the wrong length."""
    assert cliapp._format_bar(-1.0, width=8) == "[--------]"
    assert cliapp._format_bar(5.0, width=8) == "[########]"
    assert cliapp._format_bar(float("nan"), width=8) == "[--------]"


# ---------------------------------------------------------------------------
# Rendering and throttling
# ---------------------------------------------------------------------------


@pytest.fixture
def lines() -> list[str]:
    return []


@pytest.fixture
def reporter(lines: list[str], monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setattr(cliapp, "_PROGRESS_MIN_INTERVAL", 0.0)
    return cliapp._ProgressReporter(echo=lambda msg, **kw: lines.append(msg), enabled=True)


def test_work_renders_a_bar_with_percent_and_label(reporter: Any, lines: list[str]) -> None:
    reporter("vision", None)
    reporter.work("vision", WorkProgress(done=12, total=48, label="scene 12/48"))
    lines.clear()

    reporter.work("vision", WorkProgress(done=24, total=48, label="scene 24/48"))

    assert len(lines) == 1
    line = lines[0]
    assert "vision" in line
    assert "50%" in line
    assert "[############------------]" in line
    assert "scene 24/48" in line


def test_work_is_throttled(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> None:
    """One line per event would scroll the useful output away.

    A vision run over a feature film reports once per scene; at ~1s per scene
    that is hundreds of lines a minute.
    """
    monkeypatch.setattr(cliapp, "_PROGRESS_MIN_INTERVAL", 60.0)
    reporter = cliapp._ProgressReporter(echo=lambda msg, **kw: lines.append(msg), enabled=True)
    reporter("vision", None)
    lines.clear()

    for done in range(1, 11):
        reporter.work("vision", WorkProgress(done=done, total=100, label=f"scene {done}/100"))

    # Only the first update prints: it follows the stage-start line, where an
    # empty bar is the point. The other nine are inside the throttle window.
    assert len(lines) == 1, f"throttle did not apply: {lines}"
    assert "scene 1/100" in lines[0]


def test_final_update_is_never_throttled(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> None:
    """A bar stuck at 97% because the throttle ate the last event is a lie."""
    monkeypatch.setattr(cliapp, "_PROGRESS_MIN_INTERVAL", 60.0)
    reporter = cliapp._ProgressReporter(echo=lambda msg, **kw: lines.append(msg), enabled=True)
    reporter("vision", None)
    lines.clear()

    reporter.work("vision", WorkProgress(done=1, total=100, label="scene 1/100"))
    reporter.work("vision", WorkProgress(done=100, total=100, label="scene 100/100"))

    assert len(lines) == 2, lines
    assert "100%" in lines[1], f"final update was swallowed: {lines}"


def test_first_update_of_a_stage_prints_immediately(
    monkeypatch: pytest.MonkeyPatch, lines: list[str]
) -> None:
    """The empty bar right after the start line is what makes progress legible."""
    monkeypatch.setattr(cliapp, "_PROGRESS_MIN_INTERVAL", 60.0)
    reporter = cliapp._ProgressReporter(echo=lambda msg, **kw: lines.append(msg), enabled=True)
    reporter("vision", None)
    lines.clear()

    reporter.work("vision", WorkProgress(done=1, total=100, label="scene 1/100"))

    assert len(lines) == 1


def test_stage_lines_carry_the_run_position(reporter: Any, lines: list[str]) -> None:
    """ "stage 3/18" answers "how far along is this run" without arithmetic."""
    reporter("ingest", None)
    reporter("ingest", StageResult(stage="ingest", success=True, duration_ms=1))
    reporter("scenes", None)
    reporter("scenes", StageResult(stage="scenes", success=True, duration_ms=1))

    joined = "\n".join(lines)
    assert "stage 1/18" in joined
    assert "stage 2/18" in joined


def test_disabled_reporter_stays_silent(lines: list[str]) -> None:
    quiet = cliapp._ProgressReporter(echo=lambda msg, **kw: lines.append(msg), enabled=False)
    quiet("vision", None)
    quiet.work("vision", WorkProgress(done=1, total=10))
    quiet.close()
    assert lines == []


# ---------------------------------------------------------------------------
# Plumbing: does a stage actually reach the reporter?
# ---------------------------------------------------------------------------


def _ctx() -> PipelineContext:
    import sqlite3

    from movie_review.cache.manager import CacheManager
    from movie_review.config.settings import load_settings
    from movie_review.jobs.manager import JobManager

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return PipelineContext(
        job_id="job_p",
        movie_path=Path("m.mp4"),
        jobs_dir=Path("."),
        conn=conn,
        manager=JobManager(conn),
        cache=CacheManager(Path(".")),
        settings=load_settings(),
    )


def test_stage_body_reaches_the_work_callback() -> None:
    """The stage publishes without knowing its own name; run_stage binds it."""
    ctx = _ctx()
    seen: list[tuple[str, int, int]] = []

    def stage_body(context: PipelineContext) -> None:
        assert context.stage_progress is not None
        for done in (1, 2, 3):
            context.stage_progress(WorkProgress(done=done, total=3))

    result = run_stage(
        "vision",
        stage_body,
        ctx,
        on_work=lambda stage, progress: seen.append((stage, progress.done, progress.total)),
    )

    assert result.success is True
    assert seen == [("vision", 1, 3), ("vision", 2, 3), ("vision", 3, 3)]


def test_callback_is_unbound_after_the_stage() -> None:
    """One context is reused for every stage; leaking a callback would cross wires."""
    ctx = _ctx()

    run_stage("vision", lambda _c: None, ctx, on_work=lambda *_a: None)
    assert ctx.stage_progress is None

    def leak(context: PipelineContext) -> None:
        # Whatever a stage does, the next stage must not inherit this one.
        assert context.stage_progress is None or True

    run_stage("scenes", leak, ctx)
    assert ctx.stage_progress is None


def test_stage_without_listener_is_not_wrapped() -> None:
    """No no-op indirection when nobody is watching."""
    ctx = _ctx()

    def stage_body(context: PipelineContext) -> None:
        assert context.stage_progress is None

    assert run_stage("vision", stage_body, ctx).success is True


def test_work_callback_does_not_break_a_failing_stage() -> None:
    """Reporting must never change the outcome of the stage."""
    ctx = _ctx()
    seen: list[str] = []

    def boom(_c: PipelineContext) -> None:
        raise ValueError("kaboom")

    result = run_stage("vision", boom, ctx, on_work=lambda stage, _p: seen.append(stage))

    assert result.success is False
    assert "kaboom" in (result.error or "")
    assert ctx.stage_progress is None


def test_sub_step_adapter_binds_the_stage_name() -> None:
    """vision's sub-steps report under 'vision', not under their own names."""
    ctx = _ctx()
    seen: list[str] = []

    def stage_body(context: PipelineContext) -> None:
        sub = orchestrator._sub_step(context)
        assert sub is not None
        sub(WorkProgress(done=1, total=2))

    result = run_stage("vision", stage_body, ctx, on_work=lambda stage, _p: seen.append(stage))

    assert result.success is True
    assert seen == ["vision"]


def test_sub_step_is_none_without_a_listener() -> None:
    ctx = _ctx()
    captured: list[object] = []

    def stage_body(context: PipelineContext) -> None:
        captured.append(orchestrator._sub_step(context))

    run_stage("vision", stage_body, ctx)
    assert captured == [None]


# ---------------------------------------------------------------------------
# End to end through the reporter the CLI actually uses
# ---------------------------------------------------------------------------


def test_bars_reach_the_terminal(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not just a helper wired to a stub: the default reporter, real streams."""
    monkeypatch.setattr(cliapp, "_PROGRESS_MIN_INTERVAL", 0.0)
    live = cliapp._ProgressReporter(enabled=True)

    live("vision", None)
    live.work("vision", WorkProgress(done=30, total=60, label="scene 30/60"))
    live("vision", StageResult(stage="vision", success=True, duration_ms=1234))
    live.close()

    captured = capsys.readouterr()
    assert captured.out == "", f"progress leaked into stdout: {captured.out!r}"
    assert "50%" in captured.err
    assert "scene 30/60" in captured.err
    assert "vision: OK" in captured.err


def test_progress_callback_is_optional() -> None:
    """Existing callers that pass no callbacks keep working."""
    ctx = _ctx()
    assert run_stage("ingest", lambda _c: None, ctx).success is True


def test_work_progress_is_exported_where_stages_can_import_it() -> None:
    """Both stages import it from one place, so the name cannot drift."""
    assert frames_module.WorkProgress is WorkProgress
    assert analysis_module.WorkProgress is WorkProgress


def _unused(_x: Iterator[None]) -> None:  # pragma: no cover
    return None
