"""T009 acceptance: CLI skeleton parses, persists jobs, fails loudly."""

from pathlib import Path

from typer.testing import CliRunner

from movie_review.cli.app import app

runner = CliRunner()


def _db(tmp: Path) -> str:
    return str(tmp / "jobs.db")


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("process", "inspect", "validate", "resume", "retry", "version"):
        assert command in result.output


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_process_missing_file_fails(tmp_path: Path) -> None:
    result = runner.invoke(app, ["process", "absent.mp4", "--db-path", _db(tmp_path)])
    assert result.exit_code != 0


def test_process_bad_duration_fails(tmp_path: Path) -> None:
    movie = tmp_path / "m.mp4"
    movie.write_bytes(b"fake")
    result = runner.invoke(
        app, ["process", str(movie), "--duration", "soon", "--db-path", _db(tmp_path)]
    )
    assert result.exit_code != 0


def test_process_accepts_job(tmp_path: Path) -> None:
    movie = tmp_path / "m.mp4"
    movie.write_bytes(b"fake")
    result = runner.invoke(app, ["process", str(movie), "--db-path", _db(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "job_id=job_" in result.output
    job_id = result.output.split("job_id=")[1].split()[0]

    inspected = runner.invoke(app, ["inspect", job_id, "--db-path", _db(tmp_path)])
    assert inspected.exit_code == 0
    assert job_id in inspected.output

    validated = runner.invoke(app, ["validate", job_id, "--db-path", _db(tmp_path)])
    assert validated.exit_code == 0
    assert "valid=true" in validated.output


def test_unknown_job_fails(tmp_path: Path) -> None:
    assert (
        runner.invoke(app, ["inspect", "job_20990101_001", "--db-path", _db(tmp_path)]).exit_code
        != 0
    )
    assert (
        runner.invoke(app, ["validate", "job_20990101_001", "--db-path", _db(tmp_path)]).exit_code
        != 0
    )


def test_resume_retry_unimplemented(tmp_path: Path) -> None:
    movie = tmp_path / "m.mp4"
    movie.write_bytes(b"fake")
    created = runner.invoke(app, ["process", str(movie), "--db-path", _db(tmp_path)])
    job_id = created.output.split("job_id=")[1].split()[0]
    for command, owner in (("resume", "T085"), ("retry", "T070")):
        result = runner.invoke(app, [command, job_id, "--db-path", _db(tmp_path)])
        assert result.exit_code != 0
        assert "not implemented" in result.output
        assert owner in result.output
