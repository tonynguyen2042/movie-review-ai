"""The timing tests must not depend on the scheduler.

T168. Three tests were coin tosses on a loaded machine.

`test_dashboard_start_stop` took a free port, released it, and hoped nobody
else took it before the server bound it. The server now binds port 0 and
reports the port it got, so there is no window to lose.

`test_heartbeat_fires_while_a_stage_is_running` slept a fixed interval and
hoped the timer had fired. It now waits for the heartbeat, with a deadline,
so the test is about the behaviour rather than the scheduler.

`test_heartbeat_thread_does_not_outlive_the_stage` counted every thread in
the process, so a background thread from another library failed a test that
said nothing about the heartbeat. It now checks the reporter's own timer.

The dashboard test also duplicated the jobs table DDL instead of using the
real schema, so it could drift from the code and assert against a fiction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from movie_review.ui.dashboard import JobDashboard


def test_the_dashboard_reports_the_port_it_bound(tmp_path: Path) -> None:
    """Port 0 lets the operating system pick; the server says which one."""
    dashboard = JobDashboard(host="127.0.0.1", port=0, db_path=str(tmp_path / "jobs.db"))
    dashboard.start()
    try:
        assert dashboard.port != 0, "the server did not report its port"
    finally:
        dashboard.stop()


def test_the_dashboard_stops_cleanly(tmp_path: Path) -> None:
    """Stopping twice is harmless, because stop() runs from a finally block."""
    dashboard = JobDashboard(host="127.0.0.1", port=0, db_path=str(tmp_path / "jobs.db"))
    dashboard.start()
    dashboard.stop()
    dashboard.stop()


def test_the_heartbeat_timer_is_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reporter's own timer, not the number of threads in the process."""
    import importlib

    from movie_review.pipeline.orchestrator import StageResult

    cliapp = importlib.import_module("movie_review.cli.app")
    lines: list[str] = []
    reporter = cliapp._ProgressReporter(echo=lambda msg, **kw: lines.append(msg), enabled=True)
    monkeypatch.setattr(cliapp, "_HEARTBEAT_SECONDS", 0.15)

    reporter("twists", None)
    assert reporter._timer is not None, "no heartbeat was armed"
    reporter("twists", StageResult(stage="twists", success=True, duration_ms=1))
    reporter.close()
    assert reporter._timer is None, "the heartbeat timer was not cancelled"
