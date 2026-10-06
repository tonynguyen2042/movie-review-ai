"""CLI profile selection (T100).

``--quality`` shipped as a flag that named a model profile but was only copied
into the acceptance log event -- it never reached settings. The only way to pick
a profile was editing ``config/default.yaml`` or exporting an environment
variable, and the help text did not even mention ``remote``.

These tests pin that ``--profile`` is real: it changes the profile the run
actually uses, an unknown name fails as a usage error before a job exists, and
the legacy flag still works as an alias.
"""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from movie_review.cli.app import _resolve_profile, app
from movie_review.storage.database import bootstrap

# `import movie_review.cli.app as m` binds the `app` ATTRIBUTE (a Typer
# instance) rather than the module, because cli/__init__.py re-exports it.
# Patching through that alias would silently target the Typer object.
cliapp = importlib.import_module("movie_review.cli.app")

runner = CliRunner()


def _db(tmp: Path) -> str:
    return str(tmp / "jobs.db")


def _job_count(db_path: str) -> int:
    """Count job rows directly.

    JobManager exposes create/get/transition/fail but no listing query, and this
    is the one place that needs to assert a row was *not* written.
    """
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
    finally:
        conn.close()


def _movie(tmp: Path) -> Path:
    movie = tmp / "m.mp4"
    movie.write_bytes(b"fake")
    return movie


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------


def test_process_help_offers_profile() -> None:
    result = runner.invoke(app, ["process", "--help"])
    assert result.exit_code == 0
    assert "--profile" in result.output


def test_profile_help_lists_remote() -> None:
    """`remote` is the option that makes the tool usable off Apple Silicon.

    It was absent from the help text while being the only profile a Windows or
    Linux host can actually run.
    """
    result = runner.invoke(app, ["process", "--help"])
    assert "remote" in result.output


def test_deprecated_quality_is_hidden() -> None:
    """Kept working, but not advertised: two names for one flag invites doubt."""
    result = runner.invoke(app, ["process", "--help"])
    assert "--quality" not in result.output


# ---------------------------------------------------------------------------
# The flag reaches the pipeline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["resume", "retry"])
def test_other_commands_also_take_profile(command: str) -> None:
    """A job spans commands; picking a profile per command is not a feature."""
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert "--profile" in result.output


def test_profile_reaches_run_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The value must arrive in run_pipeline, not just be parsed."""
    seen: list[object] = []

    def fake_run(*_args: object, **kwargs: object) -> list[object]:
        seen.append(kwargs.get("profile"))
        return []

    monkeypatch.setattr(cliapp, "run_pipeline", fake_run)

    result = runner.invoke(
        app,
        ["process", str(_movie(tmp_path)), "--db-path", _db(tmp_path), "--profile", "remote"],
    )
    assert result.exit_code == 0, result.output
    assert seen == ["remote"]


def test_quality_alias_still_selects_the_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing invocations keep working; the rename is not a break."""
    seen: list[object] = []

    def fake_run(*_args: object, **kwargs: object) -> list[object]:
        seen.append(kwargs.get("profile"))
        return []

    monkeypatch.setattr(cliapp, "run_pipeline", fake_run)

    result = runner.invoke(
        app,
        ["process", str(_movie(tmp_path)), "--db-path", _db(tmp_path), "--quality", "remote"],
    )
    assert result.exit_code == 0, result.output
    assert seen == ["remote"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_unknown_profile_is_a_usage_error(tmp_path: Path) -> None:
    """The message must list real options, not just say 'invalid'."""
    result = runner.invoke(
        app,
        ["process", str(_movie(tmp_path)), "--db-path", _db(tmp_path), "--profile", "turbo"],
    )
    assert result.exit_code != 0
    assert "remote" in result.output


def test_unknown_profile_creates_no_job(tmp_path: Path) -> None:
    """A job that exists but can never run is worse than no job.

    The name is validated before the record is written, so a typo does not
    leave a stray CREATED row behind.
    """
    db = _db(tmp_path)
    bootstrap(db)
    result = runner.invoke(
        app, ["process", str(_movie(tmp_path)), "--db-path", db, "--profile", "turbo"]
    )
    assert result.exit_code != 0
    assert _job_count(db) == 0


def test_conflicting_flags_are_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "process",
            str(_movie(tmp_path)),
            "--db-path",
            _db(tmp_path),
            "--profile",
            "remote",
            "--quality",
            "fast",
        ],
    )
    assert result.exit_code != 0
    assert "deprecated" in result.output


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def test_resolver_passes_through_none() -> None:
    """No flag means 'leave configuration alone', not 'force balanced'."""
    assert _resolve_profile(None, None) is None


def test_resolver_accepts_every_catalog_entry() -> None:
    from movie_review.config.settings import available_profiles

    for name in available_profiles():
        assert _resolve_profile(name, None) == name
