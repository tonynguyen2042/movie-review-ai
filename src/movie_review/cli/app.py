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
from movie_review.config.settings import AppSettings, available_profiles, load_settings
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


#: Model slots that pick a runtime through ``ModelSpec.backend``.
MODEL_SLOTS = ("asr", "vision", "reasoning", "tts")


def _effective_profile(settings: AppSettings) -> str:
    """The profile actually in force, after env and flag resolution.

    The accepted-job log used to record the raw flag value, which is ``None``
    for a normal run. A reader then could not tell that ``config/default.yaml``
    had silently selected a profile that cannot work on this host -- the exact
    confusion behind a run dying 15 seconds in at the ASR stage.
    """
    return settings.models.profile


def _slot_backends(settings: AppSettings) -> dict[str, str]:
    """Per-slot ``backend:model``, for the acceptance log."""
    return {
        slot: f"{getattr(settings.models, slot).backend}:{getattr(settings.models, slot).model}"
        for slot in MODEL_SLOTS
    }


def _mlx_available_on_this_host() -> bool:
    """Whether the MLX runtime can run here at all.

    MLX is Apple-silicon-only, so on Windows or Linux a profile pinning any slot
    to ``backend: mlx`` cannot succeed. Reported as a warning rather than an
    error: a remote slot may cover the stage that would otherwise fail, and
    refusing to start would be wrong.
    """
    return sys.platform == "darwin"


def _warn_unusable_backends(settings: AppSettings) -> list[str]:
    """Warn about local slots on a host without MLX; return the slot names."""
    local = [
        slot
        for slot in MODEL_SLOTS
        if getattr(settings.models, slot).backend != "openai_compatible"
    ]
    if not local or _mlx_available_on_this_host():
        return []
    typer.echo(
        f"warning: profile {_effective_profile(settings)!r} uses the local 'mlx' backend "
        f"for {', '.join(local)}, and MLX cannot run on {sys.platform}. "
        f"That stage will fail with 'not installed'. Select a profile that routes "
        f"those slots remotely, e.g. --profile remote.",
        err=True,
    )
    return local


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

ProfileOption = Annotated[
    str | None,
    typer.Option(
        "--profile",
        help="Model profile from config/models.yaml: fast, balanced, quality, remote.",
    ),
]

# The flag used to be called --quality and did nothing: it was read into the
# acceptance log event and never reached settings, so the only way to select a
# profile was editing config/default.yaml or exporting an env var. It is kept as
# a hidden alias because it shipped, but --profile is the real name -- a
# "quality" flag that means "which models" is the same concept as profile, and
# having both invites the belief that they differ.
QualityAliasOption = Annotated[
    str | None,
    typer.Option("--quality", hidden=True),
]


def _resolve_profile(profile: str | None, quality: str | None) -> str | None:
    """Reconcile ``--profile`` with the deprecated ``--quality`` alias.

    Returns the profile name to apply, or ``None`` to leave configuration alone.

    An unknown name is rejected here, as a usage error, rather than surfacing
    later as a ``ValueError`` from the settings loader once the job is already
    created and running.
    """
    if profile and quality and profile != quality:
        raise typer.BadParameter("--quality is deprecated, use --profile; conflicting values given")
    chosen = profile or quality
    if chosen is None:
        return None
    available = available_profiles()
    if chosen not in available:
        raise typer.BadParameter(f"Unknown profile {chosen!r}; available: {', '.join(available)}")
    return chosen


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
    profile: ProfileOption = None,
    quality: QualityAliasOption = None,
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
    # Resolve the profile before creating the job, so a bad name is a usage
    # error rather than a job that exists but can never run.
    selected_profile = _resolve_profile(profile, quality)
    # Read settings with the same override the pipeline will use, so the
    # acceptance log states the profile and backends that actually run.
    effective = load_settings(profile=selected_profile)
    _warn_unusable_backends(effective)
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
            profile=_effective_profile(effective),
            profile_flag=selected_profile,
            backends=_slot_backends(effective),
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
            profile=selected_profile,
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
    profile: ProfileOption = None,
    quality: QualityAliasOption = None,
) -> None:
    """Resume an interrupted job from its last checkpoint."""
    selected_profile = _resolve_profile(profile, quality)
    # Same reasoning as process(): a resume that quietly falls back to an
    # unusable profile fails at the same stage the user is trying to escape.
    _warn_unusable_backends(load_settings(profile=selected_profile))
    manager, conn = _manager(db_path)
    with conn:
        _load_job(manager, job_id)
    reporter = _ProgressReporter(enabled=_progress_enabled())
    try:
        results = resume_job(job_id, db_path, on_progress=reporter, profile=selected_profile)
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
    profile: ProfileOption = None,
    quality: QualityAliasOption = None,
) -> None:
    """Retry a failed job or specific stage."""
    from movie_review.jobs.recovery import recovery_plan
    from movie_review.pipeline.retry import RetryPolicy, run_with_retry

    # Resolved before the retries start, so a bad name fails immediately instead
    # of once per attempt.
    selected_profile = _resolve_profile(profile, quality)
    _warn_unusable_backends(load_settings(profile=selected_profile))
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
            profile=selected_profile,
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
