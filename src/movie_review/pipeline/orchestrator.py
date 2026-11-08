"""Pipeline orchestrator: runs stages in order with checkpointing (T084, T085, T086).

Coordinates the full media→review→render pipeline using the stage contract:
validate input → cache lookup → execute → validate output → persist → metrics → complete.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from movie_review.artifacts import ArtifactRecord, IntegrityReport
from movie_review.artifacts import manager as artifacts_manager
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import AppSettings, GenerationSettings
from movie_review.domain import JobStatus, ReviewScript
from movie_review.jobs.manager import JobManager
from movie_review.jobs.recovery import recovery_plan
from movie_review.pipeline.context import StageContext
from movie_review.pipeline.model_gate import ModelCall, ModelStageDeclined, model_call_for
from movie_review.pipeline.progress import ProgressReporter, WorkProgress
from movie_review.pipeline.retry import RetryPolicy, run_with_retry
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

#: Language used when a caller states none. Matches the ASR adapter's own
#: default so the transcript, the script and TTS all agree.
DEFAULT_LANGUAGE = "en"

# Stage execution order matching T006 state machine
STAGE_SEQUENCE: list[tuple[str, str]] = [
    ("ingest", "Ingest movie metadata"),
    ("scenes", "Detect scenes"),
    ("transcript", "Transcribe dialogue"),
    ("vision", "Visual scene analysis"),
    ("characters", "Discover and link characters"),
    ("diarization", "Attribute the dialogue to speakers"),
    ("locations", "Extract locations"),
    ("events", "Extract story events"),
    ("arcs", "Extract story arcs"),
    ("themes", "Extract themes"),
    ("twists", "Detect twists"),
    ("story", "Build movie-analysis.json"),
    ("review", "Write review script"),
    ("verify", "Verify the script's claims"),
    ("review-translate", "Translate script to the target language"),
    ("tts-chunks", "Plan and synthesize TTS chunks"),
    ("tts-concat", "Concatenate narration"),
    ("tts-reconcile", "Reconcile narration duration"),
    ("render-manifest", "Build render manifest"),
    ("subtitles", "Write the subtitle sidecar"),
    ("render", "Render final video"),
    ("quality", "Run quality gate"),
]


@dataclass(frozen=True)
class StageResult:
    """Result of running one pipeline stage."""

    stage: str
    success: bool
    duration_ms: int
    error: str | None = None


class ResumeError(Exception):
    """A job cannot be resumed from where it says it failed.

    The failure is reported rather than raised as a raw ValueError from
    deep inside the pipeline: a resume that names a stage the pipeline does
    not have is a usage problem, and the CLI contract says the command
    exits non-zero with a message rather than printing a traceback.
    """


#: The failures worth another attempt. A network blip, a server that is
#: briefly busy, a model that is momentarily unreachable -- those pass on
#: their own. A schema violation, a missing input or a refusal does not,
#: and repeating it only wastes the time.
TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    TimeoutError,
    ConnectionError,
)

#: How many times a stage is attempted before it is reported as failed.
STAGE_RETRY_POLICY = RetryPolicy(max_attempts=3, backoff_seconds=2.0)


def _final_manifest(ctx: PipelineContext, job: Any, metrics: list[Any]) -> dict[str, Any]:
    """The final manifest of README section 95."""
    from movie_review.pipeline.export import build_manifest
    from movie_review.storage import repositories as repo

    movie = repo.get_movie(ctx.conn, ctx.job_id)
    models = ctx.settings.models
    return build_manifest(
        ctx.job_id,
        job.input_file,
        movie.metadata.sha256 if movie else "",
        {
            "asr": models.asr.model,
            "vision": models.vision.model,
            "reasoning": models.reasoning.model,
            "tts": models.tts.model,
        },
        {metric.name: metric.score for metric in metrics},
        job.status.value,
        {},
    )


def _record_retry(ctx: PipelineContext) -> None:
    """Count one retry on the job."""
    ctx.manager.record_retry(ctx.job_id)


def _is_transient(exc: BaseException) -> bool:
    """Whether a stage failure is worth another attempt.

    The stage errors wrap the cause that says what went wrong, so the
    chain is walked: a model that was momentarily unreachable is retryable
    even though the stage's own error type is not. The chain is guarded
    against a cycle, and the context is only followed when there is no
    explicit cause.
    """
    from movie_review.asr.port import ModelUnavailableError
    from movie_review.reasoning.port import ReasoningUnavailableError
    from movie_review.tts.port import TTSUnavailableError
    from movie_review.vision.port import VLMUnavailableError

    transient: tuple[type[Exception], ...] = TRANSIENT_ERRORS + (
        ModelUnavailableError,
        ReasoningUnavailableError,
        TTSUnavailableError,
        VLMUnavailableError,
    )

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, transient):
            return True
        current = current.__cause__ or current.__context__
    return False


@dataclass
class PipelineContext(StageContext):
    """Runtime state for pipeline execution.

    Extends :class:`StageContext` so it can be handed to any stage without
    conversion -- the stage contract only needs the context fields, plus the
    source movie for the stages that open it.

    ``stage_progress`` is set by :func:`run_stage` for the duration of a stage,
    already bound to that stage's name, so a stage publishes steps without
    knowing what it is called. It is None when nobody is listening.
    """

    movie_path: Path
    stage_progress: ProgressReporter | None = None
    #: Language the movie's dialogue is spoken in; given to ASR so it does not
    #: have to be detected, and treated as the source language for translation.
    source_language: str = DEFAULT_LANGUAGE
    #: Language the narration must end up in. Defaults to the source, which means
    #: no translation runs at all.
    target_language: str = DEFAULT_LANGUAGE

    def stage_context(self) -> StageContext:
        """The plain stage context for this run.

        Every stage takes a :class:`StageContext`, and this context already
        carries every field one needs. The stage closures used to rebuild it
        by hand, which meant a new field had to be added in eleven places.
        """
        return StageContext(
            job_id=self.job_id,
            jobs_dir=self.jobs_dir,
            conn=self.conn,
            manager=self.manager,
            cache=self.cache,
            settings=self.settings,
        )


def load_effective_script(ctx: PipelineContext) -> ReviewScript:
    """The review script in the language the narration must be spoken in.

    Every stage after translation -- chunking, concatenation, reconciliation and
    the render manifest -- reads the script through here. Four of them previously
    opened review-script.json directly, so a job that asked for another language
    would have been spoken, and subtitled, in the source one.
    """
    from movie_review.review.translate import effective_script_path, load_script

    return load_script(effective_script_path(ctx.jobs_dir, ctx.job_id, ctx.target_language))


def _sub_step(ctx: PipelineContext) -> ProgressReporter | None:
    """The progress callback for sub-steps of the running stage.

    ``run_stage`` already bound the stage name, so this only narrows the
    context field to the single-argument shape the sub-steps take, and returns
    None when nobody is listening rather than wrapping a call in a no-op that
    would still be invoked once per frame.
    """
    return ctx.stage_progress


def _stage_logger(stage: str) -> logging.Logger:
    """Logger for a pipeline stage, under the configured ``movie_review`` namespace.

    Must go through :func:`ulog.get_logger`. ``logging.getLogger(f"pipeline.{stage}")``
    builds a *different* tree at the root: ``configure_logging`` attaches its
    handler to the ``movie_review`` logger and sets ``propagate = False`` there,
    so a sibling at root reaches no handler at all and its INFO records fall to
    the root logger's default WARNING level. Every ``stage.completed`` and
    ``stage.failed`` line was silently dropped -- the one signal that tells the
    user which stage finished, or why one failed.
    """
    return ulog.get_logger(f"pipeline.{stage}")


def run_stage(
    name: str,
    fn: Callable[[PipelineContext], Any],
    ctx: PipelineContext,
    on_progress: Callable[[str, StageResult | None], None] | None = None,
    on_work: Callable[[str, WorkProgress], None] | None = None,
) -> StageResult:
    """Run a single stage with logging and error capture.

    ``on_progress`` is called with ``(name, None)`` immediately before the
    stage body runs and ``(name, result)`` once it finishes, so a caller can
    report progress while a long stage is still in flight rather than only
    after every stage has completed.

    ``on_work`` receives ``(name, WorkProgress)`` from stages that can divide
    their work. It is a separate channel from ``on_progress`` on purpose: one
    means "the stage started or ended", the other means "this is how far along
    it is", and collapsing them would leave every consumer re-deriving which is
    which.
    """
    started = time.perf_counter()
    stage_logger = _stage_logger(name)
    if on_progress is not None:
        on_progress(name, None)
    # Bind the stage name here, where it is known, so a stage can publish steps
    # without knowing what it is called. Restored afterwards because one context
    # is reused across every stage in the run.
    previous_progress = ctx.stage_progress
    ctx.stage_progress = (lambda progress: on_work(name, progress)) if on_work else None
    with ulog.logging_context(job_id=ctx.job_id, stage=name):
        try:
            # The stage's return value is intentionally unused: stages persist
            # their own artifacts and the caller reads StageResult only.
            #
            # A transient failure is retried. One network blip used to abort
            # a run that had been going for hours, and the work the stage had
            # already done was not lost -- it was in the cache -- but the
            # operator still had to start the run again.
            run_with_retry(
                lambda: fn(ctx),
                STAGE_RETRY_POLICY,
                stage=name,
                should_retry=_is_transient,
                on_retry=lambda _attempt, _exc: _record_retry(ctx),
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            ulog.log_event(
                stage_logger,
                event="stage.completed",
                status="ok",
                duration_ms=duration_ms,
            )
            result = StageResult(stage=name, success=True, duration_ms=duration_ms)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            ulog.log_event(
                stage_logger,
                event="stage.failed",
                status="error",
                duration_ms=duration_ms,
                error=str(exc),
            )
            result = StageResult(stage=name, success=False, duration_ms=duration_ms, error=str(exc))
        finally:
            ctx.stage_progress = previous_progress
    if on_progress is not None:
        on_progress(name, result)
    return result


def _build_context(
    job_id: str,
    movie_path: str | Path,
    db_path: str | None,
    profile: str | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    generation: GenerationSettings | None = None,
) -> PipelineContext:
    """Build runtime context from settings and job database.

    ``jobs_dir`` is the per-job root (``<data_dir>/jobs``), matching
    :meth:`StageContext.from_settings`, so artifacts land under
    ``<data_dir>/jobs/<job_id>/`` as the artifact layout requires.

    ``profile`` selects a ``models.yaml`` profile for this run only, overriding
    the environment and ``default.yaml``.

    ``source_language`` is given to ASR and treated as the language the review is
    written in; ``target_language`` is what the narration must end up in and
    defaults to the source, which skips translation entirely.
    """
    from movie_review.config.settings import load_settings
    from movie_review.storage.database import bootstrap

    settings = load_settings(profile=profile, generation=generation)
    data_dir = Path(settings.paths.data_dir)
    resolved_db = Path(db_path) if db_path else data_dir / "jobs.db"
    conn = sqlite3.connect(str(bootstrap(resolved_db)))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    manager = JobManager(conn)
    # Cache dir is under data_dir/cache
    cache_dir = data_dir / "cache"
    cache = CacheManager(cache_dir)
    source = source_language or DEFAULT_LANGUAGE
    return PipelineContext(
        job_id=job_id,
        jobs_dir=data_dir / "jobs",
        conn=conn,
        manager=manager,
        cache=cache,
        settings=settings,
        movie_path=Path(movie_path),
        source_language=source,
        # Not passing a target means "speak the source language", which is why
        # this falls back to the source rather than to a fixed default.
        target_language=target_language or source,
    )


def _confirm_model_stage(
    stage_name: str,
    ctx: PipelineContext,
    on_model_stage: Callable[[ModelCall], bool] | None,
) -> None:
    """Ask before a stage that needs a model, and stop the run if declined.

    Runs before :func:`run_stage` so a declined stage leaves no trace: no
    progress line is printed for it, no retry is recorded, and the job stays
    in the state the previous stage left it in -- which is what makes the
    ``resume`` after a model swap pick up at exactly this stage.
    """
    if on_model_stage is None:
        return
    call = model_call_for(
        stage_name,
        ctx.settings,
        source_language=ctx.source_language,
        target_language=ctx.target_language,
    )
    if call is None:
        return
    if on_model_stage(call):
        return
    with ulog.logging_context(job_id=ctx.job_id, stage=stage_name):
        ulog.log_event(
            _logger,
            event="model_gate.declined",
            status="ok",
            slot=call.slot,
            model=call.model,
        )
    raise ModelStageDeclined(stage_name)


def run_pipeline(
    job_id: str,
    movie_path: str | Path,
    db_path: str | None = None,
    start_stage: str | None = None,
    end_stage: str | None = None,
    on_progress: Callable[[str, StageResult | None], None] | None = None,
    profile: str | None = None,
    on_work: Callable[[str, WorkProgress], None] | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    generation: GenerationSettings | None = None,
    on_model_stage: Callable[[ModelCall], bool] | None = None,
) -> list[StageResult]:
    """Execute pipeline stages in sequence with optional start/end bounds.

    Both bounds are **inclusive**: ``start_stage="scenes", end_stage="vision"``
    runs scenes, transcript, and vision. Execution stops at the first failing
    stage so later stages never observe broken state.

    ``on_progress`` is forwarded to :func:`run_stage`; see there.
    ``on_work`` likewise receives in-stage steps.

    ``profile`` selects a ``models.yaml`` profile for this run only.
    ``source_language`` and ``target_language`` are described in
    :func:`_build_context`.

    ``on_model_stage`` is asked once before each stage that needs a model,
    with the model that stage will use. Returning False stops the run before
    that stage starts and raises :class:`ModelStageDeclined`. ``None`` -- the
    default -- runs without pausing, which is what every non-interactive
    caller wants: a test, the dashboard and the desktop app cannot answer a
    prompt, and a pipeline that blocked on one would hang rather than fail.
    """
    # Pass profile by keyword: it is a trailing option, and call sites that
    # patch this helper should not have to track its position.
    ctx = _build_context(
        job_id,
        movie_path,
        db_path,
        profile=profile,
        source_language=source_language,
        target_language=target_language,
        generation=generation,
    )
    try:
        results: list[StageResult] = []
        order = [name for name, _ in STAGE_SEQUENCE]

        if start_stage is not None and start_stage not in order:
            raise ValueError(f"Unknown start stage {start_stage!r}; expected one of {order}")
        if end_stage is not None and end_stage not in order:
            raise ValueError(f"Unknown end stage {end_stage!r}; expected one of {order}")

        begin = 0 if start_stage is None else order.index(start_stage)
        stop = len(order) if end_stage is None else order.index(end_stage) + 1
        if stop <= begin:
            # An inverted or empty range runs nothing rather than everything.
            return results

        for stage_name in order[begin:stop]:
            stage_fn = _get_stage_function(stage_name)
            if stage_fn is None:
                continue
            _confirm_model_stage(stage_name, ctx, on_model_stage)
            result = run_stage(stage_name, stage_fn, ctx, on_progress=on_progress, on_work=on_work)
            results.append(result)
            if not result.success:
                break

        return results
    finally:
        # The context owns the connection. Closing it here releases the
        # database file, which matters on Windows where an open handle keeps
        # the file locked.
        ctx.conn.close()


def _cleanup_intermediates(ctx: PipelineContext) -> None:
    """Drop the frame images the job has finished with.

    README section 83: the important artifacts are kept and the temporary
    frames are deleted after a successful analysis. A job that asked to keep
    them keeps them.
    """
    from movie_review.pipeline.cleanup import cleanup_intermediates

    job = ctx.manager.get(ctx.job_id)
    if job.keep_intermediates:
        return
    cleanup_intermediates(Path(ctx.jobs_dir) / ctx.job_id)


def _mix_music(ctx: StageContext, narration_wav: Path) -> Path:
    """Mix the music bed under the narration, when one is configured.

    The mix is written beside the narration and the mix is what the render
    muxes. A configuration with no track, or a track that is not there, means
    no bed -- the music is optional, so a missing file is not a failure.
    """
    music = ctx.settings.music
    if not music.enabled or not music.track:
        return narration_wav

    track = Path(music.track)
    if not track.is_absolute():
        track = Path(ctx.settings.paths.data_dir) / track
    if not track.is_file():
        return narration_wav

    from movie_review.rendering.audio import mix

    dest = narration_wav.with_name("narration-with-music.wav")
    try:
        mix(narration_wav, dest, music_path=track, music_gain=music.gain)
    except Exception:
        # A music bed that cannot be mixed is not worth failing the render
        # over: the narration is the product.
        return narration_wav
    return dest


def _regroup_frames(added: list[Any], frames: dict[str, list[Path]]) -> dict[str, list[Path]]:
    """The frame mapping with the feedback's extra frames folded in."""
    from movie_review.media.frames import Frame

    merged = {scene_id: list(paths) for scene_id, paths in frames.items()}
    for frame in added:
        if isinstance(frame, Frame):
            merged.setdefault(frame.scene_id, []).append(frame.path)
    for paths in merged.values():
        paths.sort()
    return merged


def job_target_seconds(ctx: PipelineContext) -> float:
    """The review length this job is aiming at, in seconds.

    The job's own target wins, because that is where the operator's
    ``--duration`` was recorded. The configured default is the fallback for
    a job created before the option existed.
    """
    job = ctx.manager.get(ctx.job_id)
    if job.target_seconds:
        return job.target_seconds
    return ctx.settings.pipeline.review.target_duration_minutes * 60


def review_target_words(settings: AppSettings, target_seconds: float | None = None) -> int:
    """The writer's word target: the target length at the configured rate.

    The speech rate comes from the configuration, not from a literal. A
    hard-coded 150 contradicted ``settings.pipeline.review.target_wpm``,
    which the reconciliation stage two stages later does use: with a
    different rate the writer was asked for 150-WPM word counts while the
    reconciler measured against the configured one, so the script came out
    systematically short and never stopped asking to be expanded.

    ``target_seconds`` overrides the configured length, which is how the
    operator's ``--duration`` reaches the writer.
    """
    from movie_review.review.duration import target_words

    seconds = (
        target_seconds
        if target_seconds is not None
        else settings.pipeline.review.target_duration_minutes * 60
    )
    return target_words(seconds, settings.pipeline.review.target_wpm)


def _get_stage_function(stage_name: str) -> Callable[[PipelineContext], Any] | None:
    """Map stage name to its execution function using lazy imports."""

    def ingest_fn(ctx: PipelineContext) -> Any:
        from movie_review.domain import JobStatus
        from movie_review.media.ingest import ingest_movie

        job = ctx.manager.get(ctx.job_id)
        if job.status in (JobStatus.CREATED, JobStatus.INGESTING):
            ctx.manager.transition(ctx.job_id, JobStatus.INGESTING)
        from movie_review.media import ffmpeg as ff

        settings = ctx.settings
        return ingest_movie(
            ctx.movie_path,
            ctx.stage_context(),
            # The configured ffprobe is used: the setting existed, and the
            # probe ignored it.
            probe_fn=lambda path: ff.probe(path, settings.media.ffprobe),
        )

    def scenes_fn(ctx: PipelineContext) -> Any:
        from movie_review.media.detection import detect_scenes_stage

        return detect_scenes_stage(
            ctx.movie_path,
            ctx.stage_context(),
        )

    def transcript_fn(ctx: PipelineContext) -> Any:
        from movie_review.asr.transcript import run_transcript

        return run_transcript(
            ctx.movie_path,
            ctx.stage_context(),
            # The CLI's --language used to be logged and then dropped, so ASR was
            # left to auto-detect every time. Told explicitly it skips a detection
            # pass and keeps the transcript's language column meaningful.
            language=ctx.source_language,
        )

    def vision_fn(ctx: PipelineContext) -> Any:
        from movie_review.media.frames import sample_movie, sampling_config_from
        from movie_review.media.proxy import generate_proxy
        from movie_review.storage import repositories as repo
        from movie_review.vision.analysis import run_visual_analysis, scene_dialogue

        scenes = repo.list_scenes(ctx.conn, ctx.job_id)
        segments = repo.list_transcript_segments(ctx.conn, ctx.job_id)

        # A downscaled analysis proxy, built once and reused. Frames are read from
        # it rather than from the source: the vision adapter inlines each frame
        # as a base64 data URI, so a 4K Blu-ray JPEG is megabytes per frame and a
        # feature film would send gigabytes to the VLM. At 720p the same frames
        # cost a fraction of that, and scene structure, blocking and action are
        # what the analysis prompt actually asks about.
        #
        # Generated here rather than as its own stage because it exists only to
        # make this stage's input cheaper; the checkpoint sequence and the job
        # state machine stay untouched. generate_proxy is idempotent (cache key
        # over the source hash and the scaling settings, re-verified against the
        # proxy's own sha256), so retries and resumes reuse it.
        proxy_settings = ctx.settings.media.proxy
        proxy = generate_proxy(
            ctx.movie_path,
            job_id=ctx.job_id,
            jobs_dir=ctx.jobs_dir,
            conn=ctx.conn,
            cache=ctx.cache,
            max_width=proxy_settings.max_width,
            max_height=proxy_settings.max_height,
            preset=proxy_settings.preset,
            crf=proxy_settings.crf,
            ffmpeg=ctx.settings.media.ffmpeg,
        )

        # Frames are the vision stage's input, sampled here for the same reason
        # the transcript stage extracts its own audio: preparation belongs to
        # the stage that needs it. This used to pass an empty dict with a "for
        # now empty" comment, so run_visual_analysis raised "No frames for
        # <scene>" on the first scene every single time.
        #
        # sample_movie is idempotent (cache key over the sampled file's hash,
        # scene spans, bucket settings and the frame rate, re-verified against
        # each frame's sha256), so a retry or resume re-uses the frames instead
        # of re-running ffmpeg.
        #
        # The fps comes from the ingest probe: the proxy keeps the source's
        # frame rate, and with it each scene's frames come from one decode
        # pass instead of one seek per frame (T179).
        movie = repo.get_movie(ctx.conn, ctx.job_id)
        sampled = sample_movie(
            proxy.path,
            [(scene.scene_id, scene.start, scene.end) for scene in scenes],
            job_id=ctx.job_id,
            jobs_dir=ctx.jobs_dir,
            conn=ctx.conn,
            cache=ctx.cache,
            config=sampling_config_from(ctx.settings.pipeline.visual_sampling),
            fps=movie.metadata.fps if movie is not None else None,
            ffmpeg=ctx.settings.media.ffmpeg,
            # run_stage left the caller's callback here, already bound to
            # "vision"; both sub-steps report through the same channel.
            on_progress=_sub_step(ctx),
        )
        # Grouped by scene, in timestamp order: sample_movie emits each scene's
        # frames consecutively and ascending, and the VLM reads them in order.
        frames: dict[str, list[Path]] = {}
        for frame in sampled.frames:
            frames.setdefault(frame.scene_id, []).append(frame.path)

        result = run_visual_analysis(
            scenes,
            frames,
            segments,
            ctx.stage_context(),
            on_progress=_sub_step(ctx),
        )

        # The frame budget is feedback-driven, not a pure function of the
        # scene's length. A scene that matters gets more frames; a scene
        # with nothing in it gets fewer. README section 12 asks for this and
        # the feedback module was written and never called.
        from movie_review.media.feedback import apply_feedback

        # The analyses are read from the database rather than from the
        # stage's return value, because that is where every other stage
        # reads them from too.
        analyses = {
            analysis.scene_id: analysis
            for analysis in repo.list_scene_analyses(ctx.conn, ctx.job_id)
        }
        items = {
            scene.scene_id: (
                analyses[scene.scene_id],
                scene_dialogue(segments, scene.start, scene.end),
            )
            for scene in scenes
            if scene.scene_id in analyses
        }
        feedback = apply_feedback(
            proxy.path,
            items,
            job_id=ctx.job_id,
            jobs_dir=ctx.jobs_dir,
            conn=ctx.conn,
            cache=ctx.cache,
            sampling_config=sampling_config_from(ctx.settings.pipeline.visual_sampling),
            ffmpeg=ctx.settings.media.ffmpeg,
        )
        if not feedback.added:
            return result

        # The extra frames are analysed too. The scenes that were already
        # analysed hit the cache, so only the boosted ones cost a call.
        boosted = _regroup_frames(feedback.added, frames)
        return run_visual_analysis(
            scenes,
            boosted,
            segments,
            ctx.stage_context(),
            on_progress=_sub_step(ctx),
        )
        return result

    def characters_fn(ctx: PipelineContext) -> Any:
        from movie_review.characters.discovery import discover_characters, save_discovery
        from movie_review.storage import repositories as repo

        scenes = repo.list_scenes(ctx.conn, ctx.job_id)
        # From the database rather than by reopening vision.json. The file
        # stays the artifact of record; this is the queryable copy, and it is
        # why the analyses survive a moved or pruned artifact tree.
        analyses_list = repo.list_scene_analyses(ctx.conn, ctx.job_id)

        scene_spans = {scene.scene_id: (scene.start, scene.end) for scene in scenes}
        segments = repo.list_transcript_segments(ctx.conn, ctx.job_id)

        # discover_characters consumes a list of analyses, not a mapping.
        result = discover_characters(analyses_list, scene_spans, segments)
        save_discovery(ctx.conn, ctx.job_id, result)

        # The job moves on to CHARACTERS_READY. Without this the whole
        # lifecycle stopped here: every later stage checks the job's status
        # before it advances it, so the events stage never reached
        # EVENTS_READY, the story stage never reached STORY_READY, and the
        # job never got past VISUAL_ANALYSIS_READY. The pipeline produced
        # every artifact, and the job never reported completion.
        job = ctx.manager.get(ctx.job_id)
        if job.status is JobStatus.VISUAL_ANALYSIS_READY:
            ctx.manager.transition(ctx.job_id, JobStatus.CHARACTERS_READY)

        # NOTE: linking characters to visual identities is not implemented.
        # characters.linking currently only provides speaker linking, which the
        # diarization stage already performs. Do not call a function that does
        # not exist here; add it when the capability lands.
        return result

    def diarization_fn(ctx: PipelineContext) -> Any:
        from movie_review.pipeline.diarization import run_diarization

        if not ctx.settings.pipeline.diarization:
            # The speakers are only needed for the speaker-to-character
            # linking, so a deployment that does not need them can turn the
            # stage off.
            return None

        # The transcript stage writes the dialogue into the audio directory;
        # looking for it in the tts directory meant the stage could never
        # find it.
        audio_path = Path(ctx.jobs_dir) / ctx.job_id / "audio" / "dialogue.wav"
        return run_diarization(audio_path, ctx)

    def locations_fn(ctx: PipelineContext) -> Any:
        from movie_review.knowledge.locations import extract_locations, scene_locations
        from movie_review.storage import repositories as repo

        scenes = repo.list_scenes(ctx.conn, ctx.job_id)
        analyses_list = repo.list_scene_analyses(ctx.conn, ctx.job_id)

        scene_spans = scene_locations(scenes)
        locations = extract_locations(analyses_list, scene_spans)

        for loc in locations:
            repo.save_location(ctx.conn, ctx.job_id, loc)
        return locations

    def events_fn(ctx: PipelineContext) -> Any:
        from movie_review.storage import repositories as repo
        from movie_review.story.events import run_event_extraction

        scenes = repo.list_scenes(ctx.conn, ctx.job_id)
        analyses = {a.scene_id: a for a in repo.list_scene_analyses(ctx.conn, ctx.job_id)}

        characters = repo.list_characters(ctx.conn, ctx.job_id)
        segments = repo.list_transcript_segments(ctx.conn, ctx.job_id)

        result = run_event_extraction(
            scenes,
            analyses,
            segments,
            characters,
            ctx.stage_context(),
        )

        # The story graph is derived from the events and persisted, so the
        # relationships table is populated and `movie-analysis.json` carries
        # the graph instead of an empty list. The builder was complete and
        # tested, and nothing called it.
        from movie_review.knowledge.graph import build_graph

        graph = build_graph(result.events)
        for relationship in graph.relationships:
            repo.save_relationship(ctx.conn, ctx.job_id, relationship)
        return result

    def arcs_fn(ctx: PipelineContext) -> Any:
        from movie_review.storage import repositories as repo
        from movie_review.story.arcs import extract_story_arcs

        events = repo.list_events(ctx.conn, ctx.job_id)
        characters = repo.list_characters(ctx.conn, ctx.job_id)
        character_lines = "\n".join(f"{c.id}: {c.name}" for c in characters)

        return extract_story_arcs(
            events,
            character_lines,
            job_id=ctx.job_id,
            jobs_dir=ctx.jobs_dir,
            conn=ctx.conn,
            cache=ctx.cache,
            spec=ctx.settings.models.reasoning,
        )

    def themes_fn(ctx: PipelineContext) -> Any:
        from movie_review.storage import repositories as repo
        from movie_review.story.themes import extract_themes

        events = repo.list_events(ctx.conn, ctx.job_id)
        characters = repo.list_characters(ctx.conn, ctx.job_id)
        character_lines = "\n".join(f"{c.id}: {c.name}" for c in characters)

        return extract_themes(
            events,
            character_lines,
            job_id=ctx.job_id,
            jobs_dir=ctx.jobs_dir,
            conn=ctx.conn,
            cache=ctx.cache,
            spec=ctx.settings.models.reasoning,
        )

    def twists_fn(ctx: PipelineContext) -> Any:
        from movie_review.storage import repositories as repo
        from movie_review.story.twists import extract_twists

        events = repo.list_events(ctx.conn, ctx.job_id)
        characters = repo.list_characters(ctx.conn, ctx.job_id)
        character_lines = "\n".join(f"{c.id}: {c.name}" for c in characters)

        return extract_twists(
            events,
            character_lines,
            job_id=ctx.job_id,
            jobs_dir=ctx.jobs_dir,
            conn=ctx.conn,
            cache=ctx.cache,
            spec=ctx.settings.models.reasoning,
        )

    def story_fn(ctx: PipelineContext) -> Any:
        from movie_review.knowledge.analysis import build_movie_analysis

        return build_movie_analysis(ctx.stage_context())

    def review_fn(ctx: PipelineContext) -> Any:
        from movie_review.review.planner import plan_review
        from movie_review.review.styles import load_style
        from movie_review.review.writer import write_script
        from movie_review.storage import repositories as repo

        # Existence guard: raises JobNotFoundError if the job is gone.
        job = ctx.manager.get(ctx.job_id)
        analysis_path = Path(ctx.jobs_dir) / ctx.job_id / "movie-analysis.json"
        import json

        with analysis_path.open() as f:
            analysis = json.load(f)

        events = repo.list_events(ctx.conn, ctx.job_id)
        # The style and the length come from the job, which is where the
        # operator's flags were recorded. Reading them from the configuration
        # instead is what made `--style documentary --duration 5m` produce a
        # 20-minute youtube-style review and report success.
        style = load_style(job.style)
        target_seconds = job.target_seconds or (
            ctx.settings.pipeline.review.target_duration_minutes * 60
        )
        target_words = review_target_words(ctx.settings, target_seconds)

        outline = plan_review(events, style, target_seconds=target_seconds)

        return write_script(
            outline,
            analysis,
            style,
            target_words,
            ctx.stage_context(),
            spec=ctx.settings.models.reasoning,
            spoilers=job.spoilers,
        )

    def verify_fn(ctx: PipelineContext) -> Any:
        from movie_review.pipeline.verify import run_verification
        from movie_review.review.translate import effective_script_path

        script_path = effective_script_path(ctx.jobs_dir, ctx.job_id, ctx.target_language)
        return run_verification(script_path, ctx)

    def review_translate_fn(ctx: PipelineContext) -> Any:
        from movie_review.review.translate import (
            load_script,
            source_script_path,
            translate_script,
        )

        source_path = source_script_path(ctx.jobs_dir, ctx.job_id)
        script = load_script(source_path)

        try:
            result = translate_script(
                script,
                ctx.stage_context(),
                source_language=ctx.source_language,
                target_language=ctx.target_language,
                # The dedicated translation slot, which falls back to reasoning
                # when a profile does not declare one.
                spec=ctx.settings.models.effective_translation,
                on_progress=_sub_step(ctx),
            )
        except Exception as exc:
            # Recorded so `retry --stage review-translate` knows where to resume,
            # the same way the transcript stage reports its own failures.
            if ctx.manager.get(ctx.job_id).status is not JobStatus.FAILED:
                ctx.manager.fail(ctx.job_id, "review-translate", str(exc))
            raise

        if result.skipped:
            # Same language in and out: no artifact, no model call, and the
            # source script stays the effective one.
            return result
        return result

    def tts_chunks_fn(ctx: PipelineContext) -> Any:
        from movie_review.tts.chunks import (
            DEFAULT_VOICE,
            plan_chunks,
            synthesize_chunks,
        )
        from movie_review.tts.factory import build_tts_adapter

        script = load_effective_script(ctx)

        # build_tts_adapter honours ModelSpec.backend; constructing QwenTTSAdapter
        # directly ignored it and required MLX on every host.
        port = build_tts_adapter(ctx.settings.models.tts)
        # Same voice constant the concat stage re-plans with, so the narration
        # metadata names the voice that actually synthesised the audio.
        chunks = plan_chunks(script, voice=DEFAULT_VOICE)
        return synthesize_chunks(
            chunks,
            port,
            ctx.jobs_dir,
            ctx.job_id,
            on_progress=_sub_step(ctx),
        )

    def tts_concat_fn(ctx: PipelineContext) -> Any:
        from movie_review.tts.chunks import (
            DEFAULT_VOICE,
            collect_chunk_results,
            plan_chunks,
        )
        from movie_review.tts.concat import NARRATION_FILENAME, concatenate

        script = load_effective_script(ctx)

        # Re-planned rather than carried in memory: concatenation is its own
        # retryable stage, and chunk IDs are positional, so the same script and
        # voice reproduce the same plan. Durations are measured from the files.
        planned = plan_chunks(script, voice=DEFAULT_VOICE)
        chunks = collect_chunk_results(planned, ctx.jobs_dir, ctx.job_id)

        # Deliberately no cache lookup: joining WAVs is pure local I/O and
        # redoing it costs a second, while a stale narration.wav would be worse.
        return concatenate(
            chunks,
            artifacts_manager.artifact_path(ctx.jobs_dir, ctx.job_id, "tts", NARRATION_FILENAME),
        )

    def tts_reconcile_fn(ctx: PipelineContext) -> Any:
        from movie_review.tts.reconcile import run_reconciliation

        script = load_effective_script(ctx)
        narration_path = Path(ctx.jobs_dir) / ctx.job_id / "tts" / "narration.wav"
        # The length the operator asked for, not the configured default.
        target_seconds = job_target_seconds(ctx)
        wpm = ctx.settings.pipeline.review.target_wpm

        return run_reconciliation(
            script,
            narration_path,
            target_seconds,
            wpm,
            ctx.stage_context(),
        )

    def render_manifest_fn(ctx: PipelineContext) -> Any:
        from movie_review.rendering.clips import select_clips
        from movie_review.rendering.manifest import ManifestError, assemble_manifest
        from movie_review.rendering.planner import plan_visuals
        from movie_review.storage import repositories as repo
        from movie_review.tts.chunks import (
            DEFAULT_VOICE,
            collect_chunk_results,
            paragraph_durations,
            plan_chunks,
        )

        script = load_effective_script(ctx)
        scenes = repo.list_scenes(ctx.conn, ctx.job_id)
        paragraphs = [p for s in script.sections for p in s.paragraphs]

        analyses = {a.scene_id: a for a in repo.list_scene_analyses(ctx.conn, ctx.job_id)}

        events = repo.list_events(ctx.conn, ctx.job_id)

        # Plan visuals
        visual_plan = plan_visuals(script, scenes, analyses, events)

        # The narration timings are measured from the synthesized audio, not
        # invented. They are the only source of the segment durations in the
        # manifest, so the timeline, the source-footage controls, the subtitle
        # timings and the renderer's own duration check all depend on them.
        #
        # The chunks are re-planned rather than carried in memory: the
        # manifest is its own retryable stage, and the plan is positional, so
        # the same script and voice reproduce the same chunk ids. Each file is
        # then measured, so a chunk that was truncated or replaced is reported
        # at its real length.
        planned = plan_chunks(script, voice=DEFAULT_VOICE)
        narration_seconds = paragraph_durations(
            collect_chunk_results(planned, ctx.jobs_dir, ctx.job_id)
        )
        missing = [p.id for p in paragraphs if p.id not in narration_seconds]
        if missing:
            # Guessing a duration here would produce a timeline that does not
            # match the audio, and a render that fails its own duration check
            # with no explanation. Say what is missing instead.
            raise ManifestError(f"No measured narration for paragraph(s): {', '.join(missing)}")

        # Resolve each paragraph's top-ranked scene into a concrete source range.
        # The planner ranks candidates; select_clips turns the top one into an
        # exact cut window (T057), which is what the manifest consumes.
        plan_scenes: dict[str, str] = {}
        for pc in visual_plan.paragraph_clips:
            plan_scenes.setdefault(pc.paragraph_id, pc.scene_id)
        clips = {
            clip.paragraph_id: clip
            for clip in select_clips(
                paragraphs,
                plan_scenes,
                scenes,
                events,
                max_clip_seconds=ctx.settings.source_video.max_clip_seconds,
                preferred_seconds=ctx.settings.source_video.preferred_clip_seconds,
            )
        }

        movie = repo.get_movie(ctx.conn, ctx.job_id)
        movie_duration = movie.metadata.duration_seconds if movie else 0

        return assemble_manifest(
            paragraphs,
            clips,
            narration_seconds,
            movie_duration,
            ctx,
            max_total_seconds=ctx.settings.source_video.max_total_seconds,
            max_source_ratio=ctx.settings.source_video.max_source_ratio,
        )

    def subtitles_fn(ctx: PipelineContext) -> Any:
        from movie_review.pipeline.subtitles import write_subtitles

        manifest_path = Path(ctx.jobs_dir) / ctx.job_id / "render" / "render-manifest.json"
        script = load_effective_script(ctx)
        return write_subtitles(manifest_path, script, ctx)

    def render_fn(ctx: PipelineContext) -> Any:
        from movie_review.rendering.manifest import read_manifest
        from movie_review.rendering.renderer import render_job

        manifest_path = Path(ctx.jobs_dir) / ctx.job_id / "render" / "render-manifest.json"

        # The file holds the manifest itself. Reading `manifest_data["manifest"]`
        # -- the cache payload's envelope -- raised KeyError on every real run,
        # so the render stage had never once succeeded.
        manifest = read_manifest(manifest_path)

        source_movie = ctx.movie_path
        narration_wav = Path(ctx.jobs_dir) / ctx.job_id / "tts" / "narration.wav"
        subtitles_srt = Path(ctx.jobs_dir) / ctx.job_id / "render" / "review.srt"

        # The music bed is mixed under the narration before the render, so the
        # video carries the mix. The mixer implements the ducking envelope
        # README section 43 asks for, and nothing called it.
        narration_wav = _mix_music(ctx, narration_wav)

        return render_job(
            manifest,
            source_movie,
            narration_wav,
            subtitles_srt if subtitles_srt.is_file() else None,
            ctx,
        )

    def quality_fn(ctx: PipelineContext) -> Any:
        from movie_review.domain import QualityMetric
        from movie_review.pipeline.export import export_output
        from movie_review.quality.characters import character_consistency
        from movie_review.quality.coverage import evidence_coverage
        from movie_review.quality.gates import run_quality_gate
        from movie_review.quality.report import build_quality_report
        from movie_review.quality.timeline import timeline_consistency
        from movie_review.quality.visual import visual_alignment
        from movie_review.rendering.manifest import read_manifest
        from movie_review.rendering.planner import plan_visuals
        from movie_review.rendering.validate import validate_render
        from movie_review.storage import repositories as repo
        from movie_review.tts.reconcile import measure_wav

        job_dir = Path(ctx.jobs_dir) / ctx.job_id

        # The metrics come from the persisted rows, not from a hard-coded
        # list. The gate thresholds in quality/gates.py -- evidence coverage
        # 90, timeline consistency 95, character consistency 95 -- are only
        # ever consulted for a metric that exists, so a stage that computed
        # none of them let every job through as COMPLETED.
        claims = repo.list_claims(ctx.conn, ctx.job_id)
        scenes = repo.list_scenes(ctx.conn, ctx.job_id)
        events = repo.list_events(ctx.conn, ctx.job_id)
        characters = repo.list_characters(ctx.conn, ctx.job_id)
        mentions = repo.list_mentions(ctx.conn, ctx.job_id)
        speaker_links = repo.list_speaker_links(ctx.conn, ctx.job_id)

        metrics: list[QualityMetric] = [
            evidence_coverage(claims),
            timeline_consistency(events, scenes),
            character_consistency(characters, mentions, speaker_links, events, scenes),
        ]

        # Visual alignment compares the plan against what was rendered, so it
        # needs both the manifest and the plan the clips were chosen from.
        manifest_path = job_dir / "render" / "render-manifest.json"
        if manifest_path.is_file():
            manifest = read_manifest(manifest_path)
            analyses = {a.scene_id: a for a in repo.list_scene_analyses(ctx.conn, ctx.job_id)}
            plan = plan_visuals(load_effective_script(ctx), scenes, analyses, events)
            metrics.append(visual_alignment(plan, manifest))

        # The duration is measured from the narration, not assumed to be the
        # target. Comparing the target with itself always yields a perfect
        # score, which is how the duration gate passed every job.
        narration_wav = job_dir / "tts" / "narration.wav"
        actual_seconds = measure_wav(narration_wav) if narration_wav.is_file() else 0.0

        target_seconds = job_target_seconds(ctx)

        gate = run_quality_gate(metrics, actual_seconds, target_seconds, ctx)

        # The render is validated against the manifest it was built from, and
        # the findings reach the report. A job whose video is missing or whose
        # segments do not line up is not a job that passed.
        validation = None
        if manifest_path.is_file():
            validation = validate_render(
                job_dir / "render" / "review.mp4",
                read_manifest(manifest_path),
                narration_wav if narration_wav.is_file() else None,
                job_dir / "render" / "review.srt",
            )

        build_quality_report(
            ctx.job_id,
            gate.metrics,
            gate,
            validation,
            ctx.jobs_dir,
            ctx.conn,
        )

        # The output set goes where the operator asked for it. The flag used
        # to reach nothing but a log line, and `paths.output_dir` was never
        # read by any code, so a run buried its results under the job
        # directory.
        job = ctx.manager.get(ctx.job_id)
        output_dir = job.output_dir or ctx.settings.paths.output_dir
        # The script is exported as Markdown. A job that never produced one
        # -- a run that stopped earlier -- exports without it rather than
        # failing the quality stage over a missing file.
        try:
            script = load_effective_script(ctx)
        except (OSError, ValueError):
            script = None
        export_output(
            ctx.jobs_dir,
            ctx.job_id,
            output_dir,
            script=script,
            manifest=_final_manifest(ctx, job, metrics),
        )
        # The job is done, so the regenerable intermediates go. A job that
        # asked to keep them keeps them.
        _cleanup_intermediates(ctx)
        return gate

    return {
        "ingest": ingest_fn,
        "scenes": scenes_fn,
        "transcript": transcript_fn,
        "vision": vision_fn,
        "characters": characters_fn,
        "diarization": diarization_fn,
        "locations": locations_fn,
        "events": events_fn,
        "arcs": arcs_fn,
        "themes": themes_fn,
        "twists": twists_fn,
        "story": story_fn,
        "review": review_fn,
        "verify": verify_fn,
        "review-translate": review_translate_fn,
        "tts-chunks": tts_chunks_fn,
        "tts-concat": tts_concat_fn,
        "tts-reconcile": tts_reconcile_fn,
        "render-manifest": render_manifest_fn,
        "subtitles": subtitles_fn,
        "render": render_fn,
        "quality": quality_fn,
    }.get(stage_name)


def resume_job(
    job_id: str,
    db_path: str | None = None,
    on_progress: Callable[[str, StageResult | None], None] | None = None,
    profile: str | None = None,
    on_work: Callable[[str, WorkProgress], None] | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    generation: GenerationSettings | None = None,
    on_model_stage: Callable[[ModelCall], bool] | None = None,
) -> list[StageResult]:
    """Resume a job from its recovery point.

    ``on_progress`` is forwarded to :func:`run_pipeline`; see there.
    ``on_work`` likewise receives in-stage steps.
    ``profile`` selects a ``models.yaml`` profile for this resume only, and the
    languages behave as they do for a fresh run. ``on_model_stage`` is the
    pause before a stage that needs a model, also as described there.
    """
    from movie_review.config.settings import load_settings
    from movie_review.storage.database import bootstrap

    settings = load_settings(generation=generation)
    resolved_db = Path(db_path) if db_path else Path(settings.paths.data_dir) / "jobs.db"
    conn = sqlite3.connect(str(bootstrap(resolved_db)))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    manager = JobManager(conn)

    try:
        plan = recovery_plan(manager, job_id)
        if plan.resume_stage in ("done", "manual"):
            return [
                StageResult(stage=plan.resume_stage, success=True, duration_ms=0, error=plan.reason)
            ]

        # The stage to resume from has to be one the pipeline knows. A failed
        # job whose `failed_stage` was never recorded -- or that names a stage
        # this build does not have -- used to reach run_pipeline, which raised
        # a ValueError that escaped the CLI as a raw traceback.
        order = [name for name, _ in STAGE_SEQUENCE]
        if plan.resume_stage not in order:
            raise ResumeError(
                f"Cannot resume {job_id}: {plan.resume_stage!r} is not a pipeline stage. "
                f"Expected one of: {', '.join(order)}"
            )

        # Get the movie path from the job
        job = manager.get(job_id)
        input_file = job.input_file
    finally:
        # Released before the pipeline opens its own connection, so a resume
        # does not hold two handles on the same database file.
        conn.close()

    return run_pipeline(
        job_id,
        input_file,
        db_path,
        start_stage=plan.resume_stage,
        on_progress=on_progress,
        profile=profile,
        on_work=on_work,
        source_language=source_language,
        target_language=target_language,
        generation=generation,
        on_model_stage=on_model_stage,
    )


def validate_job(job_id: str, db_path: str | None = None) -> IntegrityReport:
    """Check that every artifact a job recorded is present and unmodified.

    The records come from the artifacts table, which is the only place that knows
    what was written and what it hashed to. Deriving them from the job status
    instead -- which is what this did -- meant guessing filenames that were wrong
    three different ways: the stage name is not the directory several stages write
    into, the hash was left empty, and the jobs directory was off by one level. A
    job with its media.json sitting on disk and its hash in the database was
    reported invalid.

    Returns:
        An :class:`IntegrityReport`; ``passed`` is False when anything is missing,
        corrupt or names an unsafe path.
    """
    from movie_review.artifacts import scan_job_integrity
    from movie_review.config.settings import load_settings
    from movie_review.storage.database import bootstrap

    settings = load_settings()
    resolved_db = Path(db_path) if db_path else Path(settings.paths.data_dir) / "jobs.db"
    conn = sqlite3.connect(str(bootstrap(resolved_db)))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        # Raises JobNotFoundError for an unknown id, which the CLI reports as a
        # usage error rather than a traceback.
        JobManager(conn).get(job_id)

        jobs_dir = Path(settings.paths.data_dir) / "jobs"
        records, unlocated = _records_for(conn, job_id)
    finally:
        conn.close()

    report = scan_job_integrity(jobs_dir, job_id, records)
    if unlocated:
        report = replace(report, unlocated=unlocated)
    return report


def _records_for(conn: sqlite3.Connection, job_id: str) -> tuple[list[ArtifactRecord], list[str]]:
    """Records for a job's artifacts, plus the ones that name no file.

    A row without a ``relative_path`` predates schema 9. It cannot be located, and
    guessing a path for it is exactly what made validation wrong before -- so it
    is reported instead. A row without an ``output_hash`` is passed through as
    None, which checks the file exists without claiming a comparison that was
    never recorded; an empty string would instead mismatch every file.
    """
    from movie_review.storage.repositories import list_artifacts

    records: list[ArtifactRecord] = []
    unlocated: list[str] = []
    for artifact in list_artifacts(conn, job_id):
        if not artifact.relative_path:
            unlocated.append(artifact.artifact_id)
            continue
        records.append(
            ArtifactRecord(
                relative_path=artifact.relative_path,
                expected_hash=artifact.output_hash,
            )
        )
    return records, unlocated
