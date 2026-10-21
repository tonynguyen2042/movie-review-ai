"""Typer CLI (T009, T084, T085, T086, T087, T088, T089).

Commands parse arguments, wire configuration/logging/jobs, and execute the
pipeline. Stages run sequentially with checkpointing and resume support.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from movie_review import __version__
from movie_review.config.settings import AppSettings, available_profiles, load_settings
from movie_review.domain import Job, JobStatus
from movie_review.jobs.manager import JobManager
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.orchestrator import (
    STAGE_SEQUENCE,
    ResumeError,
    StageResult,
    resume_job,
    run_pipeline,
    validate_job,
)
from movie_review.pipeline.progress import WorkProgress
from movie_review.publishing.metadata import VideoMetadata
from movie_review.review.translate import TranslationError
from movie_review.storage.database import bootstrap
from movie_review.utils import logging as ulog

app = typer.Typer(help="Local-first movie-to-review pipeline.", no_args_is_help=True)

_DURATION_RE = re.compile(r"(?P<minutes>\d+)\s*m?$", re.IGNORECASE)

#: How often to report elapsed time while a stage is running, in seconds.
_HEARTBEAT_SECONDS = 10.0

#: Minimum gap between in-stage progress lines, in seconds. A vision run over a
#: feature film reports once per scene; at ~1s per scene that is hundreds of
#: lines a minute, which scrolls the useful output off the screen.
_PROGRESS_MIN_INTERVAL = 2.0

#: Width of the rendered bar in characters.
_PROGRESS_BAR_WIDTH = 24


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


#: Overrides the tty test for progress output. Truthy forces progress on, falsy
#: forces it off, unset keeps the automatic behaviour. The desktop app (T111)
#: needs this: it spawns the CLI with piped stdio, so stderr is not a terminal
#: and the tty test would silence every stage line -- leaving the app with a
#: window that shows nothing happening for hours.
_PROGRESS_ENV_VAR = "MOVIE_REVIEW_PROGRESS"
_PROGRESS_TRUE = frozenset({"1", "true", "yes", "on"})
_PROGRESS_FALSE = frozenset({"0", "false", "no", "off"})


def _progress_enabled() -> bool:
    """Silence progress lines when stderr is not a terminal.

    A heartbeat every 10s is helpful interactively and noise in a log file.
    stderr is the right stream to test because that is where progress goes.

    ``MOVIE_REVIEW_PROGRESS`` overrides the test in both directions. The
    override exists for callers that consume the progress stream themselves --
    a GUI attaching to the pipe -- and for tests, which would otherwise need a
    real terminal to exercise the reporter.
    """
    override = os.environ.get(_PROGRESS_ENV_VAR, "").strip().lower()
    if override in _PROGRESS_TRUE:
        return True
    if override in _PROGRESS_FALSE:
        return False
    return sys.stderr.isatty()


def _format_bar(fraction: float, width: int = _PROGRESS_BAR_WIDTH) -> str:
    """Render a fraction as a fixed-width bar of ``#`` and ``-``.

    The width is constant rather than proportional so the line does not jitter as
    the percentage ticks over, and it is clamped so a fraction outside [0, 1]
    from a miscounting stage cannot produce a bar of the wrong length. NaN is
    handled explicitly: comparisons against it are all False, so it would
    otherwise fall through to round() and raise.
    """
    if math.isnan(fraction):
        fraction = 0.0
    bounded = max(0.0, min(1.0, fraction))
    filled = int(round(bounded * width))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


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
        # Throttle state for in-stage bars: a vision run over a feature film
        # reports once per scene, which at ~1s each would bury the output.
        self._last_progress_at: float = 0.0
        self._completed_stages = 0

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
                # Force the first bar of a new stage to print immediately: the
                # stage-start line is the only thing on screen, and an empty bar
                # right after it is what makes progress legible.
                self._last_progress_at = 0.0
            self._echo(
                f"  -> {stage} (stage {self._completed_stages + 1}/{len(STAGE_SEQUENCE)}) ..."
            )
            self._schedule_heartbeat()
            return

        with self._lock:
            self._cancel_timer()
            elapsed = time.perf_counter() - (self._stage_started or time.perf_counter())
            self._stage_name = None
            self._stage_started = None
            self._completed_stages += 1
        verdict = "OK" if result.success else "FAILED"
        self._echo(
            f"  {stage}: {verdict} ({_format_elapsed(elapsed)}, "
            f"stage {self._completed_stages}/{len(STAGE_SEQUENCE)})"
        )
        if result.error:
            self._echo(f"    error: {result.error}")

    def work(self, stage: str, progress: WorkProgress) -> None:
        """Render an in-stage bar for stages that can divide their work.

        Throttled by time rather than printed per event. A stage that reports
        hundreds of times a minute would otherwise scroll the start line, the
        heartbeat and the result off the screen -- the very output that answers
        "is it hung?".

        The final update always prints: a bar that stops at 97% because the
        throttle swallowed the last event would be worse than no bar at all.
        """
        if not self._enabled:
            return
        now = time.perf_counter()
        with self._lock:
            finished = progress.total > 0 and progress.done >= progress.total
            if not finished and now - self._last_progress_at < _PROGRESS_MIN_INTERVAL:
                return
            self._last_progress_at = now
            elapsed = time.perf_counter() - self._stage_started if self._stage_started else 0.0

        parts = [f"  {stage} {_format_bar(progress.fraction)} {progress.percent:3d}%"]
        if progress.label:
            parts.append(f"  {progress.label}")
        parts.append(f"({_format_elapsed(elapsed)})")
        self._echo(" ".join(parts))

    def close(self) -> None:
        """Stop any pending heartbeat, e.g. after a keyboard interrupt."""
        with self._lock:
            self._cancel_timer()
            self._stage_name = None
            self._stage_started = None


#: Model slots that pick a runtime through ``ModelSpec.backend``. ``translation``
#: is optional, so it is resolved rather than read: a profile without one borrows
#: reasoning and must not be reported twice.
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
    slots = {name: getattr(settings.models, name) for name in MODEL_SLOTS}
    slots["translation"] = settings.models.effective_translation
    return {name: f"{spec.backend}:{spec.model}" for name, spec in slots.items()}


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
    candidates: dict[str, str] = {
        name: getattr(settings.models, name).backend for name in MODEL_SLOTS
    }
    candidates["translation"] = settings.models.effective_translation.backend
    # A translation slot that merely borrows reasoning is the same local model,
    # so it is not reported twice.
    if settings.models.translation is None:
        candidates.pop("translation")
    local = sorted(name for name, backend in candidates.items() if backend != "openai_compatible")
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


def _resolve_languages(source: str, target: str | None) -> tuple[str, str]:
    """Validate the source language and settle the narration language.

    An omitted target means the narration is spoken in the source language, which
    skips translation entirely. Both tags are validated here so a typo is a usage
    error rather than a job that fails several stages later with an unusable
    filename.
    """
    from movie_review.review.translate import validate_language

    try:
        source_tag = validate_language(source)
        target_tag = validate_language(target) if target else source_tag
    except TranslationError as exc:
        raise typer.BadParameter(str(exc)) from exc
    return source_tag, target_tag


def _validate_stage(value: str) -> str:
    """Check a stage name against the pipeline, as a usage error.

    A stage name the pipeline does not have used to reach `run_pipeline`,
    which raised a ValueError that escaped as a raw traceback. The stage may
    also come from a job's recorded `failed_stage`, which need not name a
    stage this build has.
    """
    order = [name for name, _ in STAGE_SEQUENCE]
    if value not in order:
        raise typer.BadParameter(f"Unknown stage {value!r}; expected one of {order}")
    return value


def _manager(db_path: str | None) -> tuple[JobManager, sqlite3.Connection]:
    settings = load_settings()
    resolved = Path(db_path) if db_path else Path(settings.paths.data_dir) / "jobs.db"
    conn = sqlite3.connect(str(bootstrap(resolved)))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return JobManager(conn), conn


@contextmanager
def _session(db_path: str | None) -> Iterator[tuple[JobManager, sqlite3.Connection]]:
    """A job manager and its connection, closed on the way out.

    The connection used to be opened and never closed. The process exited
    with it still open, which on Windows keeps the database file locked and
    leaves the handle open for anything else that wants the file.
    """
    manager, conn = _manager(db_path)
    try:
        yield manager, conn
    finally:
        conn.close()


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
    language: Annotated[
        str,
        typer.Option(
            help="Source language: the movie's dialogue, and the language the review is written in."
        ),
    ] = "en",
    target_language: Annotated[
        str | None,
        typer.Option(
            "--target-language",
            help="Narration language. Defaults to --language, so nothing is translated.",
        ),
    ] = None,
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
    # An omitted target means "speak the source language", so the fallback is the
    # source rather than any fixed default: no translation, no extra model calls.
    source_language, narration_language = _resolve_languages(language, target_language)
    # Resolve the profile before creating the job, so a bad name is a usage
    # error rather than a job that exists but can never run.
    selected_profile = _resolve_profile(profile, quality)
    # Read settings with the same override the pipeline will use, so the
    # acceptance log states the profile and backends that actually run.
    effective = load_settings(profile=selected_profile)
    _warn_unusable_backends(effective)
    with _session(db_path) as (manager, conn):
        with conn:
            job = manager.create(movie)
    with ulog.logging_context(job_id=job.job_id, stage="cli"):
        ulog.log_event(
            ulog.get_logger("cli"),
            event="cli.process.accepted",
            status="ok",
            language=source_language,
            target_language=narration_language,
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
            on_work=reporter.work,
            profile=selected_profile,
            source_language=source_language,
            target_language=narration_language,
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
    with _session(db_path) as (manager, conn):
        with conn:
            job = _load_job(manager, job_id)
    typer.echo(json.dumps(job.model_dump(mode="json"), indent=2, sort_keys=True))


@app.command()
def validate(
    job_id: Annotated[str, typer.Argument(help="Job ID.")], db_path: DbOption = None
) -> None:
    """Check that a job's recorded artifacts are present and unmodified."""
    # validate_job loads the job itself, so resolve it here first to report an
    # unknown ID as a usage error instead of a traceback.
    with _session(db_path) as (manager, conn):
        with conn:
            job = _load_job(manager, job_id)

    report = validate_job(job_id, db_path)

    typer.echo(f"job_id={job.job_id} status={job.status.value} valid={report.passed}")
    typer.echo(f"  artifacts checked : {report.checked}")
    typer.echo(f"  verified          : {report.ok}")
    for label, items in (
        ("missing", report.missing),
        ("corrupt", report.corrupt),
        ("unsafe path", report.unsafe),
    ):
        for item in items:
            typer.echo(f"  {label:<17}: {item}", err=True)
    if report.unlocated:
        # Not a failure: these rows predate schema 9 and name no file, so nothing
        # could be checked for them. Saying so beats implying they were verified.
        typer.echo(
            f"  not recorded      : {len(report.unlocated)} artifact row(s) name no file",
            err=True,
        )
    if not report.checked and not report.unlocated:
        typer.echo("  no artifacts recorded for this job yet", err=True)
    if not report.passed:
        raise typer.Exit(code=1)


@app.command()
def resume(
    job_id: Annotated[str, typer.Argument(help="Job ID.")],
    db_path: DbOption = None,
    profile: ProfileOption = None,
    quality: QualityAliasOption = None,
    language: Annotated[str, typer.Option(help="Source language of the movie.")] = "en",
    target_language: Annotated[
        str | None, typer.Option("--target-language", help="Narration language.")
    ] = None,
) -> None:
    """Resume an interrupted job from its last checkpoint."""
    selected_profile = _resolve_profile(profile, quality)
    # A resume has to state the languages again: the job record never held them,
    # so without this a translated job would quietly continue in the source one.
    source_language, narration_language = _resolve_languages(language, target_language)
    # Same reasoning as process(): a resume that quietly falls back to an
    # unusable profile fails at the same stage the user is trying to escape.
    _warn_unusable_backends(load_settings(profile=selected_profile))
    with _session(db_path) as (manager, conn):
        with conn:
            _load_job(manager, job_id)
    reporter = _ProgressReporter(enabled=_progress_enabled())
    try:
        results = resume_job(
            job_id,
            db_path,
            on_progress=reporter,
            on_work=reporter.work,
            profile=selected_profile,
            source_language=source_language,
            target_language=narration_language,
        )
    except KeyboardInterrupt:
        reporter.close()
        typer.echo("Interrupted. Job state is preserved; use 'resume' to continue.", err=True)
        raise typer.Exit(code=130) from None
    except ResumeError as exc:
        reporter.close()
        typer.echo(f"Cannot resume {job_id}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
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
    language: Annotated[str, typer.Option(help="Source language of the movie.")] = "en",
    target_language: Annotated[
        str | None, typer.Option("--target-language", help="Narration language.")
    ] = None,
) -> None:
    """Retry a failed job or specific stage."""
    from movie_review.jobs.recovery import recovery_plan
    from movie_review.pipeline.retry import RetryPolicy, run_with_retry

    # Resolved before the retries start, so a bad name fails immediately instead
    # of once per attempt.
    selected_profile = _resolve_profile(profile, quality)
    source_language, narration_language = _resolve_languages(language, target_language)
    _warn_unusable_backends(load_settings(profile=selected_profile))
    with _session(db_path) as (manager, conn):
        with conn:
            job = _load_job(manager, job_id)

        if job.status != JobStatus.FAILED:
            typer.echo(
                f"Job {job_id} is not in FAILED state (current: {job.status.value})", err=True
            )
            raise typer.Exit(code=1)

        # The recovery plan reads the job, so it has to be asked while the
        # connection is still open.
        plan = recovery_plan(manager, job_id)
        target_stage = _validate_stage(stage or plan.resume_stage)

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
            on_work=reporter.work,
            profile=selected_profile,
            source_language=source_language,
            target_language=narration_language,
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


@app.command("publish-platforms")
def publish_platforms() -> None:
    """List supported publishing platforms and whether each can upload here."""
    from movie_review.publishing.registry import build_adapter, platform_names, unavailable_reason

    typer.echo("Supported platforms:")
    for name in platform_names():
        adapter = build_adapter(name)
        if adapter.available():
            typer.echo(f"  {name}: ready")
        else:
            typer.echo(f"  {name}: unavailable -- {unavailable_reason(name, adapter)}", err=True)
    typer.echo(
        "\nCredentials come from the environment "
        "(MOVIE_REVIEW_FACEBOOK_PAGE_ID, MOVIE_REVIEW_FACEBOOK_TOKEN, "
        "MOVIE_REVIEW_TIKTOK_TOKEN), never from config files."
    )


@app.command()
def publish(
    job_id: Annotated[str, typer.Argument(help="Job ID.")],
    platform: Annotated[
        str, typer.Option("--platform", help="youtube, facebook or tiktok.")
    ] = "youtube",
    db_path: DbOption = None,
    profile: ProfileOption = None,
    language: Annotated[str, typer.Option(help="Target language for the metadata.")] = "en",
    privacy: Annotated[str, typer.Option(help="Privacy level for the upload.")] = "unlisted",
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Actually upload. Without it, only preview."),
    ] = False,
    title_override: Annotated[
        str | None, typer.Option("--title", help="Use this title instead of the generated one.")
    ] = None,
    description_override: Annotated[
        str | None, typer.Option("--description", help="Use this description instead.")
    ] = None,
) -> None:
    """Generate metadata for a rendered video and optionally upload it.

    Nothing leaves this machine unless ``--confirm`` is passed. The default
    prints the title, description and tags and stops, so a title can be read and
    judged before it becomes public.

    Copyright: this makes no claim that any clip duration or percentage is
    legally safe. That determination depends on actual use and jurisdiction.
    """
    from movie_review.publishing.registry import build_adapter, is_platform, platform_names

    if not is_platform(platform):
        raise typer.BadParameter(
            f"Unknown platform {platform!r}; expected one of {', '.join(platform_names())}"
        )
    _resolve_languages(language, None)
    selected_profile = _resolve_profile(profile, None)
    settings = load_settings(profile=selected_profile)
    _warn_unusable_backends(settings)

    with _session(db_path) as (manager, conn):
        with conn:
            job = _load_job(manager, job_id)

    from movie_review.pipeline.context import StageContext
    from movie_review.publishing.ai_metadata import (
        PublishingMetadataError,
        generate_publishing_metadata,
        metadata_path,
        recorded_video_path,
    )
    from movie_review.publishing.metadata import build_chapters
    from movie_review.publishing.thumbnail import thumbnail_path
    from movie_review.review.translate import effective_script_path, load_script

    ctx = StageContext.from_settings(settings, conn, job_id)
    video = recorded_video_path(ctx)
    if video is None:
        typer.echo(
            f"No rendered video for {job_id}. Run the pipeline through the render stage first.",
            err=True,
        )
        raise typer.Exit(code=1)

    # The translated script when the job produced one, the source otherwise --
    # the same rule every downstream stage follows, so the packaging describes the
    # video that was actually rendered.
    script = load_script(effective_script_path(ctx.jobs_dir, job_id, language))
    chapters = build_chapters(script)

    existing = metadata_path(ctx.jobs_dir, job_id)
    if existing.is_file() and not confirm:
        from movie_review.publishing.ai_metadata import load_metadata

        metadata = load_metadata(existing)
        typer.echo(f"Using existing metadata: {existing}", err=True)
    else:
        try:
            result = generate_publishing_metadata(
                script,
                ctx,
                movie_title=_movie_title(job.input_file),
                platform=platform,
                target_language=language,
                spec=settings.models.reasoning,
                chapters=chapters,
            )
        except PublishingMetadataError as exc:
            typer.echo(f"Could not generate metadata: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        metadata = result.metadata
        typer.echo(
            f"Generated metadata (model={result.model}, prompt={result.prompt_version}, "
            f"cache_hit={result.cache_hit})",
            err=True,
        )

    if title_override:
        metadata = _with_title(metadata, title_override)
    if description_override:
        metadata = _with_description(metadata, description_override)

    typer.echo("")
    typer.echo(f"Video   : {video}")
    typer.echo(f"Platform: {platform}  privacy={privacy}")
    typer.echo(f"Title   : {metadata.title}")
    typer.echo("")
    typer.echo("Description:")
    typer.echo(metadata.description)
    typer.echo("")
    typer.echo(f"Tags    : {', '.join(metadata.tags)}")
    typer.echo("")

    if not confirm:
        typer.echo("Preview only. Re-run with --confirm to upload.")
        return

    from movie_review.publishing.port import PublishingError, UploadRequest

    try:
        adapter = build_adapter(platform)
        if not adapter.available():
            from movie_review.publishing.registry import unavailable_reason

            typer.echo(
                f"{platform} cannot upload here: {unavailable_reason(platform, adapter)}",
                err=True,
            )
            raise typer.Exit(code=1)
        thumb = thumbnail_path(ctx.jobs_dir, job_id)
        receipt = adapter.upload(
            UploadRequest(
                video_path=video,
                metadata=metadata,
                thumbnail_path=thumb if thumb.is_file() else None,
                privacy=privacy,
            )
        )
    except PublishingError as exc:
        typer.echo(f"Upload failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Uploaded: {receipt.url or receipt.video_id} (status={receipt.status})")


def _movie_title(input_file: str) -> str:
    """The movie's title from its path: the file stem, whatever the separator.

    The title is sent to the model and embedded in the published YouTube,
    Facebook and TikTok metadata, so it must not carry the operator's
    directory layout. Splitting on "/" alone did that on Windows, where a
    path has no forward slash: `D:\\Movies\\film.mkv` became
    `D:\\Movies\\film`.
    """
    return Path(input_file).stem


def _with_title(metadata: VideoMetadata, title: str) -> VideoMetadata:
    """Metadata with a caller-supplied title, for a human edit before upload."""
    from dataclasses import replace

    return replace(metadata, title=title)


def _with_description(metadata: VideoMetadata, description: str) -> VideoMetadata:
    """Metadata with a caller-supplied description."""
    from dataclasses import replace

    return replace(metadata, description=description)


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
