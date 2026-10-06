"""Typer CLI (T009, T084, T085, T086, T087, T088, T089).

Commands parse arguments, wire configuration/logging/jobs, and execute the
pipeline. Stages run sequentially with checkpointing and resume support.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from movie_review import __version__
from movie_review.config.settings import load_settings
from movie_review.domain import Job
from movie_review.jobs.manager import JobManager
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.orchestrator import (
    STAGE_SEQUENCE,
    StageResult,
    resume_job,
    run_pipeline,
    validate_job,
)
from movie_review.storage.database import bootstrap
from movie_review.utils import logging as ulog

app = typer.Typer(help="Local-first movie-to-review pipeline.", no_args_is_help=True)

_DURATION_RE = re.compile(r"(?P<minutes>\d+)\s*m?$", re.IGNORECASE)

#: How often to report elapsed time while a stage is running, in seconds.
_HEARTBEAT_SECONDS = 10.0


def _parse_duration(value: str) -> int:
    """Parse ``20m``/``20`` into minutes or raise :class:`typer.BadParameter`."""
    match = _DURATION_RE.fullmatch(value.strip())
    if not match or int(match.group("minutes")) <= 0:
        raise typer.BadParameter(f"Invalid duration {value!r}: expected like '20m'")
    return int(match.group("minutes"))


def _format_elapsed(seconds: float) -> str:
    """Render elapsed seconds as ``12s`` or ``3m05s`` for progress lines."""
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    return f"{total // 60}m{total % 60:02d}s"


def _progress_enabled() -> bool:
    """Silence progress lines when stderr is not a terminal.

    A heartbeat every 10s is helpful interactively and noise in a log file.
    stderr is the right stream to test because that is where progress goes.
    """
    return sys.stderr.isatty()


class _ProgressReporter:
    """Print each stage as it starts and finishes, with a liveness heartbeat.

    Without this the CLI printed results only after every stage had run, so a
    multi-hour pipeline looked identical to a hung one. The heartbeat thread
    exists because a single stage (transcription, TTS, rendering) can run for
    many minutes with no output of its own; it proves the process is alive and
    how long the current stage has been going.

    Progress goes to stderr, leaving stdout free for machine-readable output.
    """

    def __init__(
        self,
        echo: Callable[..., None] | None = None,
        enabled: bool = True,
    ) -> None:
        self._echo_fn: Callable[..., None] = echo if echo is not None else typer.echo
        self._enabled = enabled
        self._lock = threading.Lock()
        self._stage_started: float | None = None
        self._stage_name: str | None = None
        self._timer: threading.Timer | None = None

    def _echo(self, message: str) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._echo_fn(message, err=True)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _heartbeat(self) -> None:
        """Emit an elapsed-time line and reschedule until the stage ends."""
        with self._lock:
            if self._stage_started is None or self._stage_name is None:
                return
            elapsed = time.perf_counter() - self._stage_started
            name = self._stage_name
        self._echo(f"    ... {name} still running ({_format_elapsed(elapsed)})")
        # Re-check under the lock before rescheduling: the stage may have
        # finished between the read above and here, and a timer armed after
        # _cancel_timer would print one bogus line for a finished stage.
        with self._lock:
            if self._stage_started is None:
                return
            timer = threading.Timer(_HEARTBEAT_SECONDS, self._heartbeat)
            timer.daemon = True
            self._timer = timer
            timer.start()

    def _schedule_heartbeat(self) -> None:
        if not self._enabled:
            return
        with self._lock:
            if self._stage_started is None:
                return
            timer = threading.Timer(_HEARTBEAT_SECONDS, self._heartbeat)
            timer.daemon = True
            self._timer = timer
            timer.start()

    def __call__(self, stage: str, result: StageResult | None) -> None:
        if result is None:
            with self._lock:
                self._stage_name = stage
                self._stage_started = time.perf_counter()
            self._echo(f"  -> {stage} ...")
            self._schedule_heartbeat()
            return

        with self._lock:
            self._cancel_timer()
            elapsed = time.perf_counter() - (self._stage_started or time.perf_counter())
            self._stage_name = None
            self._stage_started = None
        verdict = "OK" if result.success else "FAILED"
        self._echo(f"  {stage}: {verdict} ({_format_elapsed(elapsed)})")
        if result.error:
            self._echo(f"    error: {result.error}")

    def close(self) -> None:
        """Stop any pending heartbeat, e.g. after a keyboard interrupt."""
        with self._lock:
            self._cancel_timer()
            self._stage_name = None
            self._stage_started = None


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
    stage_from: Annotated[
        str | None, typer.Option("--stage-from", help="Start from stage (T086).")
    ] = None,
    stage_to: Annotated[
        str | None, typer.Option("--stage-to", help="Run up to stage (T086).")
    ] = None,
    no_run: Annotated[
        bool, typer.Option("--no-run", help="Create job only, do not run pipeline.")
    ] = False,
) -> None:
    """Accept a movie, create a job, and optionally run the full pipeline."""
    if not Path(movie).is_file():
        raise typer.BadParameter(f"Input file not found: {movie}")
    # Validate stage names before creating the job, so a typo is reported as a
    # usage error instead of raising mid-pipeline and leaving a stray record.
    order = [name for name, _ in STAGE_SEQUENCE]
    for flag, value in (("--stage-from", stage_from), ("--stage-to", stage_to)):
        if value is not None and value not in order:
            raise typer.BadParameter(f"Invalid value for '{flag}': {value!r} is not one of {order}")
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

    if no_run:
        typer.echo("Pipeline execution skipped (--no-run). Use 'resume' to start.")
        return

    # Run the pipeline, reporting each stage as it starts and finishes so a
    # long run is visibly progressing rather than silent.
    reporter = _ProgressReporter(enabled=_progress_enabled())
    try:
        results = run_pipeline(
            job.job_id,
            movie,
            db_path,
            start_stage=stage_from,
            end_stage=stage_to,
            on_progress=reporter,
        )
    except KeyboardInterrupt:
        reporter.close()
        typer.echo("Interrupted. Job state is preserved; use 'resume' to continue.", err=True)
        raise typer.Exit(code=130) from None

    if any(not r.success for r in results):
        raise typer.Exit(code=1)


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
    """Check a job record is well-formed and validate its artifacts."""
    # validate_job loads the job itself, so resolve it here first to report an
    # unknown ID as a usage error instead of a traceback.
    manager, conn = _manager(db_path)
    with conn:
        job = _load_job(manager, job_id)
    is_valid = validate_job(job_id, db_path)
    typer.echo(f"job_id={job.job_id} status={job.status.value} valid={is_valid}")
    if not is_valid:
        raise typer.Exit(code=1)


@app.command()
def resume(
    job_id: Annotated[str, typer.Argument(help="Job ID.")],
    db_path: DbOption = None,
) -> None:
    """Resume an interrupted job from its last checkpoint."""
    manager, conn = _manager(db_path)
    with conn:
        _load_job(manager, job_id)
    reporter = _ProgressReporter(enabled=_progress_enabled())
    try:
        results = resume_job(job_id, db_path, on_progress=reporter)
    except KeyboardInterrupt:
        reporter.close()
        typer.echo("Interrupted. Job state is preserved; use 'resume' to continue.", err=True)
        raise typer.Exit(code=130) from None
    if any(not r.success for r in results):
        raise typer.Exit(code=1)


@app.command()
def retry(
    job_id: Annotated[str, typer.Argument(help="Job ID.")],
    db_path: DbOption = None,
    stage: Annotated[
        str | None, typer.Option("--stage", help="Specific stage to retry (T070).")
    ] = None,
) -> None:
    """Retry a failed job or specific stage."""
    from movie_review.jobs.recovery import recovery_plan
    from movie_review.pipeline.retry import RetryPolicy, run_with_retry

    manager, conn = _manager(db_path)
    with conn:
        job = _load_job(manager, job_id)

    if job.status != job.status.FAILED:
        typer.echo(f"Job {job_id} is not in FAILED state (current: {job.status.value})", err=True)
        raise typer.Exit(code=1)

    # Get recovery plan to find failed stage
    plan = recovery_plan(manager, job_id)
    target_stage = stage or plan.resume_stage

    typer.echo(f"Retrying stage: {target_stage}")

    # Run with retry policy
    policy = RetryPolicy(max_attempts=3, backoff_seconds=2.0)

    reporter = _ProgressReporter(enabled=_progress_enabled())

    def _run_stage() -> StageResult:
        results = run_pipeline(
            job_id,
            job.input_file,
            db_path,
            start_stage=target_stage,
            end_stage=target_stage,
            on_progress=reporter,
        )
        if not results or not results[0].success:
            raise RuntimeError(
                f"Stage {target_stage} failed: {results[0].error if results else 'no result'}"
            )
        return results[0]

    try:
        run_with_retry(_run_stage, policy, stage=target_stage)
        typer.echo(f"Stage {target_stage} succeeded on retry")
    except KeyboardInterrupt:
        reporter.close()
        typer.echo("Interrupted.", err=True)
        raise typer.Exit(code=130) from None
    except Exception as exc:
        typer.echo(f"Retry exhausted for {target_stage}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        reporter.close()


@app.command()
def stages() -> None:
    """List available pipeline stages in execution order (T086)."""
    for stage_name, desc in STAGE_SEQUENCE:
        typer.echo(f"  {stage_name}: {desc}")


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def dashboard(
    host: Annotated[str, typer.Option(help="Host to bind to.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8080,
    db_path: DbOption = None,
    open_browser: Annotated[bool, typer.Option(help="Open browser on start.")] = False,
) -> None:
    """Start the web job dashboard (T089)."""
    from movie_review.ui.dashboard import run_dashboard

    typer.echo(f"Starting dashboard at http://{host}:{port}")
    typer.echo("Press Ctrl+C to stop")
    dashboard = run_dashboard(host, port, db_path, open_browser)
    try:
        # Keep running until interrupted
        import time

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        typer.echo("\nStopping dashboard...")
        dashboard.stop()
