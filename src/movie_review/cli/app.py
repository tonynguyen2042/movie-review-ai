"""Typer CLI skeleton (T009).

Commands parse arguments, wire configuration/logging/jobs, and persist job
records. Stage execution itself arrives with later phases; unimplemented
operations fail loudly instead of pretending to work.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Annotated

import typer

from movie_review import __version__
from movie_review.config.settings import load_settings
from movie_review.domain import Job
from movie_review.jobs.manager import JobManager
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.storage.database import bootstrap
from movie_review.utils import logging as ulog

app = typer.Typer(help="Local-first movie-to-review pipeline.", no_args_is_help=True)

_DURATION_RE = re.compile(r"(?P<minutes>\d+)\s*m?$", re.IGNORECASE)


def _parse_duration(value: str) -> int:
    """Parse ``20m``/``20`` into minutes or raise :class:`typer.BadParameter`."""
    match = _DURATION_RE.fullmatch(value.strip())
    if not match or int(match.group("minutes")) <= 0:
        raise typer.BadParameter(f"Invalid duration {value!r}: expected like '20m'")
    return int(match.group("minutes"))


def _manager(db_path: str | None) -> tuple[JobManager, sqlite3.Connection]:
    settings = load_settings()
    resolved = Path(db_path) if db_path else Path(settings.paths.data_dir) / "jobs.db"
    conn = sqlite3.connect(str(bootstrap(resolved)))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return JobManager(conn), conn


def _load_job(manager: JobManager, job_id: str) -> Job:
    try:
        return manager.get(job_id)
    except JobNotFoundError as exc:
        raise typer.BadParameter(f"Unknown job: {job_id}") from exc


DbOption = Annotated[
    str | None,
    typer.Option("--db-path", help="Jobs database file (default: <data_dir>/jobs.db)."),
]


@app.callback()
def _startup(
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug logging.")] = False,
) -> None:
    settings = load_settings()
    ulog.configure_logging(level="DEBUG" if verbose else settings.logging.level)


@app.command()
def process(
    movie: Annotated[str, typer.Argument(help="Input movie file.")],
    language: Annotated[str, typer.Option(help="Review language.")] = "en",
    duration: Annotated[str, typer.Option(help="Target review length, e.g. '20m'.")] = "20m",
    style: Annotated[str, typer.Option(help="Review style profile.")] = "youtube",
    quality: Annotated[
        str, typer.Option(help="Model profile: fast, balanced, quality.")
    ] = "balanced",
    spoilers: Annotated[str, typer.Option(help="Spoiler level.")] = "full",
    output: Annotated[str, typer.Option(help="Output directory.")] = "./output",
    db_path: DbOption = None,
) -> None:
    """Accept a movie, persist a job record, and queue it for processing."""
    if not Path(movie).is_file():
        raise typer.BadParameter(f"Input file not found: {movie}")
    minutes = _parse_duration(duration)
    manager, conn = _manager(db_path)
    with conn:
        job = manager.create(movie)
    with ulog.logging_context(job_id=job.job_id, stage="cli"):
        ulog.log_event(
            ulog.get_logger("cli"),
            event="cli.process.accepted",
            status="ok",
            language=language,
            target_minutes=minutes,
            style=style,
            quality=quality,
            spoilers=spoilers,
            output=output,
        )
    typer.echo(f"job_id={job.job_id} status={job.status.value}")
    typer.echo("Pipeline stages arrive in later phases (T010+); job is queued.")


@app.command()
def inspect(
    job_id: Annotated[str, typer.Argument(help="Job ID.")], db_path: DbOption = None
) -> None:
    """Print a job record as JSON."""
    manager, conn = _manager(db_path)
    with conn:
        job = _load_job(manager, job_id)
    typer.echo(json.dumps(job.model_dump(mode="json"), indent=2, sort_keys=True))


@app.command()
def validate(
    job_id: Annotated[str, typer.Argument(help="Job ID.")], db_path: DbOption = None
) -> None:
    """Check a job record is well-formed and report its state."""
    manager, conn = _manager(db_path)
    with conn:
        job = _load_job(manager, job_id)
    typer.echo(f"job_id={job.job_id} status={job.status.value} valid=true")


@app.command()
def resume(
    job_id: Annotated[str, typer.Argument(help="Job ID.")], db_path: DbOption = None
) -> None:
    """Resume an interrupted job (full behavior in T085)."""
    manager, conn = _manager(db_path)
    with conn:
        _load_job(manager, job_id)
    typer.echo("resume is not implemented yet (T085); job state unchanged.", err=True)
    raise typer.Exit(code=1)


@app.command()
def retry(job_id: Annotated[str, typer.Argument(help="Job ID.")], db_path: DbOption = None) -> None:
    """Retry a failed job (full behavior in T070)."""
    manager, conn = _manager(db_path)
    with conn:
        _load_job(manager, job_id)
    typer.echo("retry is not implemented yet (T070); job state unchanged.", err=True)
    raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)
