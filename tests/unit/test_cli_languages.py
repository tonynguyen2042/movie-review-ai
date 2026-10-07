"""The CLI's two language options (T107).

``--language`` used to be accepted and then dropped: it reached the acceptance
log and nothing else. ``--target-language`` is new, and omitting it means the
narration is spoken in the source language -- no translation, no model calls.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

cliapp = importlib.import_module("movie_review.cli.app")
from movie_review.cli.app import _resolve_languages, app  # noqa: E402

runner = CliRunner()


def _movie(tmp_path: Path) -> Path:
    movie = tmp_path / "m.mp4"
    movie.write_bytes(b"fake")
    return movie


def _db(tmp_path: Path) -> str:
    return str(tmp_path / "jobs.db")


def _accepted(output: str) -> dict[str, Any]:
    for line in output.splitlines():
        if "cli.process.accepted" in line:
            parsed: dict[str, Any] = json.loads(line)
            return parsed
    raise AssertionError(f"no acceptance event in {output!r}")


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


def test_process_help_offers_both_languages() -> None:
    result = runner.invoke(app, ["process", "--help"])
    assert result.exit_code == 0
    assert "--language" in result.output
    assert "--target-language" in result.output


@pytest.mark.parametrize("command", ["resume", "retry"])
def test_resume_and_retry_accept_the_languages(command: str) -> None:
    """A job spans commands; a translated job must not continue in the source one."""
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert "--target-language" in result.output


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_target_defaults_to_the_source() -> None:
    """The requested behaviour, verbatim: no target means the language value."""
    assert _resolve_languages("vi", None) == ("vi", "vi")


def test_explicit_target_wins() -> None:
    assert _resolve_languages("vi", "en") == ("vi", "en")


def test_tags_are_normalised() -> None:
    assert _resolve_languages(" VI ", "EN") == ("vi", "en")


def test_a_bad_source_tag_is_a_usage_error() -> None:
    from typer import BadParameter

    with pytest.raises(BadParameter):
        _resolve_languages("not a language", None)


def test_a_bad_target_tag_is_a_usage_error() -> None:
    from typer import BadParameter

    with pytest.raises(BadParameter):
        _resolve_languages("vi", "../escape")


def test_a_path_traversal_tag_is_rejected(tmp_path: Path) -> None:
    """The tag becomes a filename; it cannot address outside the job directory."""
    result = runner.invoke(
        app,
        [
            "process",
            str(_movie(tmp_path)),
            "--db-path",
            _db(tmp_path),
            "--target-language",
            "../../etc",
        ],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# What actually reaches the pipeline
# ---------------------------------------------------------------------------


def test_languages_reach_run_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(
        job_id: str, movie_path: str, db_path: str | None = None, **kwargs: Any
    ) -> list[Any]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(cliapp, "run_pipeline", fake_run)

    result = runner.invoke(
        app,
        [
            "process",
            str(_movie(tmp_path)),
            "--db-path",
            _db(tmp_path),
            "--language",
            "vi",
            "--target-language",
            "en",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen["source_language"] == "vi"
    assert seen["target_language"] == "en"


def test_omitted_target_is_passed_as_the_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pipeline still needs an explicit value; the default is the source."""
    seen: dict[str, Any] = {}

    def _fake_run(
        job_id: str, movie_path: str, db_path: str | None = None, **kwargs: Any
    ) -> list[Any]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(cliapp, "run_pipeline", _fake_run)

    result = runner.invoke(
        app, ["process", str(_movie(tmp_path)), "--db-path", _db(tmp_path), "--language", "vi"]
    )

    assert result.exit_code == 0, result.output
    assert seen["source_language"] == "vi"
    assert seen["target_language"] == "vi"


def test_acceptance_log_records_both(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "process",
            str(_movie(tmp_path)),
            "--db-path",
            _db(tmp_path),
            "--language",
            "vi",
            "--target-language",
            "en",
            "--no-run",
        ],
    )
    assert result.exit_code == 0, result.output
    event = _accepted(result.output)
    assert event["language"] == "vi"
    assert event["target_language"] == "en"


def test_no_job_is_created_for_a_bad_tag(tmp_path: Path) -> None:
    from movie_review.storage.database import bootstrap

    db = _db(tmp_path)
    bootstrap(db)
    result = runner.invoke(
        app, ["process", str(_movie(tmp_path)), "--db-path", db, "--target-language", "!!"]
    )
    assert result.exit_code != 0

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    finally:
        conn.close()
