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
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from movie_review.cli.app import _resolve_profile, app
from movie_review.pipeline.orchestrator import StageResult
from movie_review.storage.database import bootstrap
from tests.helpers import (
    _db,
)

# `import movie_review.cli.app as m` binds the `app` ATTRIBUTE (a Typer
# instance) rather than the module, because cli/__init__.py re-exports it.
# Patching through that alias would silently target the Typer object.
cliapp = importlib.import_module("movie_review.cli.app")

runner = CliRunner()


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


def _movie__cli_profile(tmp: Path) -> Path:
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
        return [StageResult(stage="ingest", success=True, duration_ms=0)]

    monkeypatch.setattr(cliapp, "run_pipeline", fake_run)

    result = runner.invoke(
        app,
        [
            "process",
            str(_movie__cli_profile(tmp_path)),
            "--db-path",
            _db(tmp_path),
            "--profile",
            "remote",
        ],
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
        return [StageResult(stage="ingest", success=True, duration_ms=0)]

    monkeypatch.setattr(cliapp, "run_pipeline", fake_run)

    result = runner.invoke(
        app,
        [
            "process",
            str(_movie__cli_profile(tmp_path)),
            "--db-path",
            _db(tmp_path),
            "--quality",
            "remote",
        ],
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
        [
            "process",
            str(_movie__cli_profile(tmp_path)),
            "--db-path",
            _db(tmp_path),
            "--profile",
            "turbo",
        ],
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
        app, ["process", str(_movie__cli_profile(tmp_path)), "--db-path", db, "--profile", "turbo"]
    )
    assert result.exit_code != 0
    assert _job_count(db) == 0


def test_conflicting_flags_are_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "process",
            str(_movie__cli_profile(tmp_path)),
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
# The acceptance log must name the profile that actually runs
# ---------------------------------------------------------------------------


def _accepted_log(output: str) -> dict[str, Any]:
    for line in output.splitlines():
        if "cli.process.accepted" in line:
            parsed: dict[str, Any] = json.loads(line)
            return parsed
    raise AssertionError(f"no acceptance event in output: {output!r}")


def test_log_states_the_effective_profile_not_just_the_flag(tmp_path: Path) -> None:
    """`profile: null` told the reader nothing.

    Without --profile the flag value is None and the profile actually in force
    comes from config/default.yaml. Logging only the flag made a run that had
    silently chosen an unusable profile look unconfigured.
    """
    result = runner.invoke(
        app,
        ["process", str(_movie__cli_profile(tmp_path)), "--db-path", _db(tmp_path), "--no-run"],
    )
    assert result.exit_code == 0, result.output
    event = _accepted_log(result.output)
    assert event["profile"] is not None
    assert event["profile"] == "balanced"
    assert event["profile_flag"] is None


def test_log_states_the_profile_when_flagged(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "process",
            str(_movie__cli_profile(tmp_path)),
            "--db-path",
            _db(tmp_path),
            "--no-run",
            "--profile",
            "remote",
        ],
    )
    assert result.exit_code == 0, result.output
    event = _accepted_log(result.output)
    assert event["profile"] == "remote"
    assert event["profile_flag"] == "remote"


def test_log_states_each_slot_backend(tmp_path: Path) -> None:
    """Which slot runs locally and which goes remote is the whole question."""
    result = runner.invoke(
        app,
        [
            "process",
            str(_movie__cli_profile(tmp_path)),
            "--db-path",
            _db(tmp_path),
            "--no-run",
            "--profile",
            "remote",
        ],
    )
    assert result.exit_code == 0, result.output
    backends = _accepted_log(result.output)["backends"]
    assert set(backends) == {"asr", "vision", "reasoning", "tts", "translation"}
    assert backends["asr"].startswith("openai_compatible:")


def test_translation_slot_is_logged_even_when_borrowed(tmp_path: Path) -> None:
    """The log answers "which model will translate", not "did I configure one"."""
    result = runner.invoke(
        app,
        ["process", str(_movie__cli_profile(tmp_path)), "--db-path", _db(tmp_path), "--no-run"],
    )
    assert result.exit_code == 0, result.output
    backends = _accepted_log(result.output)["backends"]
    models = cliapp.load_settings().models
    assert backends["translation"] == (
        f"{models.effective_translation.backend}:{models.effective_translation.model}"
    )


# ---------------------------------------------------------------------------
# Guardrail: MLX cannot run on this host
# ---------------------------------------------------------------------------


def test_warns_when_a_local_slot_cannot_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """The failure it prevents costs minutes of audio extraction first."""
    monkeypatch.setattr(cliapp, "_mlx_available_on_this_host", lambda: False)
    settings = cliapp.load_settings(profile="balanced")

    warned: list[str] = []
    monkeypatch.setattr(cliapp.typer, "echo", lambda msg, **kw: warned.append(msg))

    # Sorted, and no "translation": this profile borrows reasoning, so listing
    # it separately would point the operator at a slot they never configured.
    assert cliapp._warn_unusable_backends(settings) == ["asr", "reasoning", "tts", "vision"]
    assert settings.models.translation is None
    assert any("cannot run on" in m for m in warned)


def test_no_warning_when_slots_are_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    """A remote profile is the fix; it must not also emit a warning."""
    monkeypatch.setattr(cliapp, "_mlx_available_on_this_host", lambda: False)
    settings = cliapp.load_settings(profile="remote")

    warned: list[str] = []
    monkeypatch.setattr(cliapp.typer, "echo", lambda msg, **kw: warned.append(msg))

    assert cliapp._warn_unusable_backends(settings) == []
    assert warned == []


def test_no_warning_on_apple_silicon(monkeypatch: pytest.MonkeyPatch) -> None:
    """MLX runs there, so the same profile is correct and must stay quiet."""
    monkeypatch.setattr(cliapp, "_mlx_available_on_this_host", lambda: True)
    warned: list[str] = []
    monkeypatch.setattr(cliapp.typer, "echo", lambda msg, **kw: warned.append(msg))

    assert cliapp._warn_unusable_backends(cliapp.load_settings(profile="balanced")) == []
    assert warned == []


def test_warning_reaches_the_terminal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Not just a helper that works when called directly."""
    monkeypatch.setattr(cliapp, "_mlx_available_on_this_host", lambda: False)
    result = runner.invoke(
        app,
        ["process", str(_movie__cli_profile(tmp_path)), "--db-path", _db(tmp_path), "--no-run"],
    )
    assert result.exit_code == 0
    assert "MLX cannot run on" in result.output


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
