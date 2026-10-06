"""CLI acceptance tests (T009 skeleton, T084-T088 full commands)."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from movie_review.cli.app import app

runner = CliRunner()


def _db(tmp: Path) -> str:
    return str(tmp / "jobs.db")


def _mock_ffprobe(*args, **kwargs):
    """Mock ffprobe to return valid media metadata for fake files."""
    from movie_review.domain import MovieMetadata

    return MovieMetadata(
        file="test.mp4",
        sha256="a" * 64,
        duration_seconds=120.0,
        width=1920,
        height=1080,
        fps=30.0,
        video_codec="h264",
        audio_codec="aac",
        container="mp4",
    )


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("process", "inspect", "validate", "resume", "retry", "version", "stages"):
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
    """Process creates job (with --no-run for T009 compatibility)."""
    movie = tmp_path / "m.mp4"
    movie.write_bytes(b"fake")
    result = runner.invoke(app, ["process", str(movie), "--no-run", "--db-path", _db(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "job_id=job_" in result.output
    job_id = result.output.split("job_id=")[1].split()[0]

    inspected = runner.invoke(app, ["inspect", job_id, "--db-path", _db(tmp_path)])
    assert inspected.exit_code == 0
    assert job_id in inspected.output

    validated = runner.invoke(app, ["validate", job_id, "--db-path", _db(tmp_path)])
    assert validated.exit_code == 0
    assert "valid=True" in validated.output


def test_unknown_job_fails(tmp_path: Path) -> None:
    assert (
        runner.invoke(app, ["inspect", "job_20990101_001", "--db-path", _db(tmp_path)]).exit_code
        != 0
    )
    assert (
        runner.invoke(app, ["validate", "job_20990101_001", "--db-path", _db(tmp_path)]).exit_code
        != 0
    )


def test_resume_retry(tmp_path: Path) -> None:
    """Resume and retry commands now implemented (T085, T070)."""
    movie = tmp_path / "m.mp4"
    movie.write_bytes(b"fake")
    with patch("movie_review.media.ffmpeg.probe", side_effect=_mock_ffprobe):
        created = runner.invoke(app, ["process", str(movie), "--db-path", _db(tmp_path)])
    job_id = created.output.split("job_id=")[1].split()[0]

    # resume should run (may fail due to missing artifacts, but not "not implemented")
    result = runner.invoke(app, ["resume", job_id, "--db-path", _db(tmp_path)])
    assert result.exit_code != 0  # fails because no artifacts, but not "not implemented"
    assert "not implemented" not in result.output

    # retry should run
    result = runner.invoke(app, ["retry", job_id, "--db-path", _db(tmp_path)])
    assert result.exit_code != 0  # fails because job not FAILED
    assert "not implemented" not in result.output


def test_stages_command(tmp_path: Path) -> None:
    """Stages command lists pipeline stages (T086)."""
    result = runner.invoke(app, ["stages"])
    assert result.exit_code == 0
    assert "ingest" in result.output
    assert "render" in result.output
