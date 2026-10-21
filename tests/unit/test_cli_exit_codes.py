"""A command that did nothing must not report success.

T131 regression. Two defects in the CLI.

`run_pipeline` returns an empty result list for an inverted stage range, and
`any(not r.success for r in results)` over an empty list is False -- so
`process --stage-from quality --stage-to ingest` exited 0 having done
nothing at all.

The progress reporter's heartbeat is a timer thread, and `reporter.close()`
was only called on `KeyboardInterrupt`. After any other failure the timer
kept firing, so the command printed "... <stage> still running" lines long
after it had given up. The `retry` command already did it correctly with a
`finally`.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from movie_review.cli.app import app


def _movie(tmp_path: Path) -> Path:
    movie = tmp_path / "movie.mp4"
    movie.write_bytes(b"\x00\x00\x00\x18ftypmp42not-a-video")
    return movie


def test_an_inverted_stage_range_is_a_usage_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "process",
            str(_movie(tmp_path)),
            "--db-path",
            str(tmp_path / "jobs.db"),
            "--stage-from",
            "quality",
            "--stage-to",
            "ingest",
        ],
    )
    assert result.exit_code == 2, result.output
    assert "Traceback" not in (result.stdout or "") + (result.stderr or "")
    assert "comes before" in (result.stdout or "") + (result.stderr or "")


def test_a_range_that_runs_nothing_is_not_a_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even if an empty run slips through, it is a failure.

    The range is rejected up front, so this covers the belt-and-braces
    branch: a run that produced no stage results has done nothing, and
    `any` over an empty list is False, which is how the command used to
    report success.
    """
    import importlib

    # The package re-exports the Typer object as `app`, so the module has to
    # be imported by name to reach the functions it holds.
    cli_module = importlib.import_module("movie_review.cli.app")
    monkeypatch.setattr(cli_module, "run_pipeline", lambda *a, **k: [])
    result = CliRunner().invoke(
        cli_module.app,
        [
            "process",
            str(_movie(tmp_path)),
            "--db-path",
            str(tmp_path / "jobs.db"),
        ],
    )
    assert result.exit_code != 0, result.output
    assert "ran no stages" in (result.stdout or "") + (result.stderr or "")


def test_the_reporter_is_closed_on_a_failure(tmp_path: Path) -> None:
    """The heartbeat must not survive the command that started it."""
    before = threading.active_count()
    result = CliRunner().invoke(
        app,
        [
            "process",
            str(_movie(tmp_path)),
            "--db-path",
            str(tmp_path / "jobs.db"),
            "--stage-from",
            "quality",
            "--stage-to",
            "ingest",
        ],
    )
    assert result.exit_code == 2
    # No timer thread is left running by the rejected command.
    assert threading.active_count() <= before + 1


def test_a_valid_range_is_accepted(tmp_path: Path) -> None:
    """The check must not reject a range the pipeline can run."""
    result = CliRunner().invoke(
        app,
        [
            "process",
            str(_movie(tmp_path)),
            "--db-path",
            str(tmp_path / "jobs.db"),
            "--no-run",
            "--stage-from",
            "ingest",
            "--stage-to",
            "scenes",
        ],
    )
    assert result.exit_code == 0, result.output
