"""The operator's flags have to reach the pipeline.

T119 regression. `process` parsed `--duration`, `--style`, `--spoilers` and
`--output`, then used all four only in a log event. The pipeline read its
length and style from the configuration instead, so `--duration 5m --style
documentary` produced a 20-minute youtube-style review and reported success.

These tests cover the whole path: the CLI stores the options on the job, the
job keeps them across a reload, and the review stage reads them.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from movie_review.cache.manager import CacheManager
from movie_review.cli.app import app
from movie_review.config.settings import load_settings
from movie_review.domain import Job
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.orchestrator import PipelineContext, job_target_seconds
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _run_process(tmp_path: Path, *args: str) -> str:
    """Run `process --no-run` and return the created job id."""
    movie = tmp_path / "movie.mp4"
    movie.write_bytes(b"\x00\x00\x00\x18ftypmp42not-a-video")
    result = CliRunner().invoke(
        app,
        [
            "process",
            str(movie),
            "--db-path",
            str(tmp_path / "jobs.db"),
            "--no-run",
            *args,
        ],
    )
    assert result.exit_code == 0, result.output
    job_id = next(
        line.split("=", 1)[1].split()[0]
        for line in result.output.splitlines()
        if line.startswith("job_id=")
    )
    return job_id


def test_the_duration_is_stored_on_the_job(tmp_path: Path) -> None:
    job_id = _run_process(tmp_path, "--duration", "5m")
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    try:
        job = repo.get_job(conn, job_id)
        assert job is not None
        assert job.target_seconds == 300.0
    finally:
        conn.close()


def test_the_style_is_stored_on_the_job(tmp_path: Path) -> None:
    job_id = _run_process(tmp_path, "--style", "documentary")
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    try:
        job = repo.get_job(conn, job_id)
        assert job is not None
        assert job.style == "documentary"
    finally:
        conn.close()


def test_the_spoilers_are_stored_on_the_job(tmp_path: Path) -> None:
    job_id = _run_process(tmp_path, "--spoilers", "none")
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    try:
        job = repo.get_job(conn, job_id)
        assert job is not None
        assert job.spoilers == "none"
    finally:
        conn.close()


def test_the_output_directory_is_stored_on_the_job(tmp_path: Path) -> None:
    job_id = _run_process(tmp_path, "--output", str(tmp_path / "out"))
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    try:
        job = repo.get_job(conn, job_id)
        assert job is not None
        assert job.output_dir == str(tmp_path / "out")
    finally:
        conn.close()


def test_the_options_survive_a_reload(tmp_path: Path) -> None:
    """The job row is the only record that survives a resume."""
    job_id = _run_process(tmp_path, "--duration", "7m", "--style", "serious")
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    try:
        first = repo.get_job(conn, job_id)
        assert first is not None
        assert (first.target_seconds, first.style) == (420.0, "serious")
    finally:
        conn.close()

    conn2 = connect(bootstrap(tmp_path / "jobs.db"))
    try:
        second = repo.get_job(conn2, job_id)
        assert second is not None
        assert (second.target_seconds, second.style) == (420.0, "serious")
    finally:
        conn2.close()


def test_the_review_stage_reads_the_options_from_the_job(tmp_path: Path) -> None:
    """The target the stages use is the one the operator asked for."""
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(
        conn,
        Job(
            job_id="job_1",
            input_file="m.mp4",
            style="documentary",
            spoilers="none",
            target_seconds=300.0,
            output_dir=str(tmp_path / "out"),
        ),
    )
    ctx = PipelineContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
        movie_path=tmp_path / "movie.mp4",
    )
    assert job_target_seconds(ctx) == 300.0

    job = manager.get("job_1")
    assert job.style == "documentary"
    assert job.spoilers == "none"
    conn.close()


def test_a_job_without_a_target_uses_the_configured_default(tmp_path: Path) -> None:
    """A job created before the option existed still has a length."""
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    ctx = PipelineContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
        movie_path=tmp_path / "movie.mp4",
    )
    assert job_target_seconds(ctx) == 20 * 60
    conn.close()


def test_the_output_set_is_copied_to_the_output_directory(tmp_path: Path) -> None:
    """--output has to receive the files, not just be logged."""
    from movie_review.pipeline.export import export_output

    job_dir = tmp_path / "jobs" / "job_1"
    (job_dir / "render").mkdir(parents=True)
    (job_dir / "tts").mkdir(parents=True)
    (job_dir / "render" / "review.mp4").write_bytes(b"video")
    (job_dir / "tts" / "narration.wav").write_bytes(b"audio")

    out = tmp_path / "out"
    written = export_output(tmp_path / "jobs", "job_1", out)

    assert {p.name for p in written} == {"review.mp4", "narration.wav"}
    assert (out / "review.mp4").read_bytes() == b"video"
    assert (out / "narration.wav").read_bytes() == b"audio"


def test_a_job_record_round_trips_the_options(tmp_path: Path) -> None:
    """The repository must not drop the columns it now writes."""
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    try:
        job = Job(
            job_id="job_1",
            input_file="m.mp4",
            style="funny",
            spoilers="light",
            target_seconds=120.0,
            output_dir="/tmp/out",
        )
        repo.save_job(conn, job)
        loaded = repo.get_job(conn, "job_1")
        assert loaded is not None
        assert loaded.style == "funny"
        assert loaded.spoilers == "light"
        assert loaded.target_seconds == 120.0
        assert loaded.output_dir == "/tmp/out"
    finally:
        conn.close()
