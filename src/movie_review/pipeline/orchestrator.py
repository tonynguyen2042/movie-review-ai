"""Pipeline orchestrator: runs stages in order with checkpointing (T084, T085, T086).

Coordinates the full media→review→render pipeline using the stage contract:
validate input → cache lookup → execute → validate output → persist → metrics → complete.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from movie_review.artifacts import ArtifactRecord
from movie_review.artifacts import manager as artifacts_manager
from movie_review.cache.manager import CacheManager
from movie_review.jobs.manager import JobManager
from movie_review.jobs.recovery import recovery_plan
from movie_review.pipeline.context import StageContext
from movie_review.pipeline.progress import ProgressReporter, WorkProgress
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

# Stage execution order matching T006 state machine
STAGE_SEQUENCE: list[tuple[str, str]] = [
    ("ingest", "Ingest movie metadata"),
    ("scenes", "Detect scenes"),
    ("transcript", "Transcribe dialogue"),
    ("vision", "Visual scene analysis"),
    ("characters", "Discover and link characters"),
    ("locations", "Extract locations"),
    ("events", "Extract story events"),
    ("arcs", "Extract story arcs"),
    ("themes", "Extract themes"),
    ("twists", "Detect twists"),
    ("story", "Build movie-analysis.json"),
    ("review", "Write review script"),
    ("tts-chunks", "Plan and synthesize TTS chunks"),
    ("tts-concat", "Concatenate narration"),
    ("tts-reconcile", "Reconcile narration duration"),
    ("render-manifest", "Build render manifest"),
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
            fn(ctx)
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
) -> PipelineContext:
    """Build runtime context from settings and job database.

    ``jobs_dir`` is the per-job root (``<data_dir>/jobs``), matching
    :meth:`StageContext.from_settings`, so artifacts land under
    ``<data_dir>/jobs/<job_id>/`` as the artifact layout requires.

    ``profile`` selects a ``models.yaml`` profile for this run only, overriding
    the environment and ``default.yaml``.
    """
    from movie_review.config.settings import load_settings
    from movie_review.storage.database import bootstrap

    settings = load_settings(profile=profile)
    data_dir = Path(settings.paths.data_dir)
    resolved_db = Path(db_path) if db_path else data_dir / "jobs.db"
    conn = sqlite3.connect(str(bootstrap(resolved_db)))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    manager = JobManager(conn)
    # Cache dir is under data_dir/cache
    cache_dir = data_dir / "cache"
    cache = CacheManager(cache_dir)
    return PipelineContext(
        job_id=job_id,
        jobs_dir=data_dir / "jobs",
        conn=conn,
        manager=manager,
        cache=cache,
        settings=settings,
        movie_path=Path(movie_path),
    )


def run_pipeline(
    job_id: str,
    movie_path: str | Path,
    db_path: str | None = None,
    start_stage: str | None = None,
    end_stage: str | None = None,
    on_progress: Callable[[str, StageResult | None], None] | None = None,
    profile: str | None = None,
    on_work: Callable[[str, WorkProgress], None] | None = None,
) -> list[StageResult]:
    """Execute pipeline stages in sequence with optional start/end bounds.

    Both bounds are **inclusive**: ``start_stage="scenes", end_stage="vision"``
    runs scenes, transcript, and vision. Execution stops at the first failing
    stage so later stages never observe broken state.

    ``on_progress`` is forwarded to :func:`run_stage`; see there.
    ``on_work`` likewise receives in-stage steps.

    ``profile`` selects a ``models.yaml`` profile for this run only.
    """
    # Pass profile by keyword: it is a trailing option, and call sites that
    # patch this helper should not have to track its position.
    ctx = _build_context(job_id, movie_path, db_path, profile=profile)
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
        result = run_stage(stage_name, stage_fn, ctx, on_progress=on_progress, on_work=on_work)
        results.append(result)
        if not result.success:
            break

    return results


def _get_stage_function(stage_name: str) -> Callable[[PipelineContext], Any] | None:
    """Map stage name to its execution function using lazy imports."""

    def ingest_fn(ctx: PipelineContext) -> Any:
        from movie_review.domain import JobStatus
        from movie_review.media.ingest import ingest_movie

        job = ctx.manager.get(ctx.job_id)
        if job.status in (JobStatus.CREATED, JobStatus.INGESTING):
            ctx.manager.transition(ctx.job_id, JobStatus.INGESTING)
        return ingest_movie(
            ctx.movie_path,
            StageContext(
                job_id=ctx.job_id,
                jobs_dir=ctx.jobs_dir,
                conn=ctx.conn,
                manager=ctx.manager,
                cache=ctx.cache,
                settings=ctx.settings,
            ),
        )

    def scenes_fn(ctx: PipelineContext) -> Any:
        from movie_review.media.detection import detect_scenes_stage

        return detect_scenes_stage(
            ctx.movie_path,
            StageContext(
                job_id=ctx.job_id,
                jobs_dir=ctx.jobs_dir,
                conn=ctx.conn,
                manager=ctx.manager,
                cache=ctx.cache,
                settings=ctx.settings,
            ),
        )

    def transcript_fn(ctx: PipelineContext) -> Any:
        from movie_review.asr.transcript import run_transcript

        return run_transcript(
            ctx.movie_path,
            StageContext(
                job_id=ctx.job_id,
                jobs_dir=ctx.jobs_dir,
                conn=ctx.conn,
                manager=ctx.manager,
                cache=ctx.cache,
                settings=ctx.settings,
            ),
        )

    def vision_fn(ctx: PipelineContext) -> Any:
        from movie_review.media.frames import sample_movie, sampling_config_from
        from movie_review.media.proxy import generate_proxy
        from movie_review.storage import repositories as repo
        from movie_review.vision.analysis import run_visual_analysis

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
        # scene spans and bucket settings, re-verified against each frame's
        # sha256), so a retry or resume re-uses the frames instead of re-running
        # ffmpeg.
        sampled = sample_movie(
            proxy.path,
            [(scene.scene_id, scene.start, scene.end) for scene in scenes],
            job_id=ctx.job_id,
            jobs_dir=ctx.jobs_dir,
            conn=ctx.conn,
            cache=ctx.cache,
            config=sampling_config_from(ctx.settings.pipeline.visual_sampling),
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

        return run_visual_analysis(
            scenes,
            frames,
            segments,
            StageContext(
                job_id=ctx.job_id,
                jobs_dir=ctx.jobs_dir,
                conn=ctx.conn,
                manager=ctx.manager,
                cache=ctx.cache,
                settings=ctx.settings,
            ),
            on_progress=_sub_step(ctx),
        )

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

        # NOTE: linking characters to visual identities is not implemented.
        # characters.linking currently only provides speaker linking, which the
        # diarization stage already performs. Do not call a function that does
        # not exist here; add it when the capability lands.
        return result

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

        return run_event_extraction(
            scenes,
            analyses,
            segments,
            characters,
            StageContext(
                job_id=ctx.job_id,
                jobs_dir=ctx.jobs_dir,
                conn=ctx.conn,
                manager=ctx.manager,
                cache=ctx.cache,
                settings=ctx.settings,
            ),
        )

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
            model=ctx.settings.models.reasoning.model,
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
            model=ctx.settings.models.reasoning.model,
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
            model=ctx.settings.models.reasoning.model,
        )

    def story_fn(ctx: PipelineContext) -> Any:
        from movie_review.knowledge.analysis import build_movie_analysis

        return build_movie_analysis(
            StageContext(
                job_id=ctx.job_id,
                jobs_dir=ctx.jobs_dir,
                conn=ctx.conn,
                manager=ctx.manager,
                cache=ctx.cache,
                settings=ctx.settings,
            )
        )

    def review_fn(ctx: PipelineContext) -> Any:
        from movie_review.review.planner import plan_review
        from movie_review.review.styles import load_style
        from movie_review.review.writer import write_script
        from movie_review.storage import repositories as repo

        # Existence guard: raises JobNotFoundError if the job is gone.
        ctx.manager.get(ctx.job_id)
        analysis_path = Path(ctx.jobs_dir) / ctx.job_id / "movie-analysis.json"
        import json

        with analysis_path.open() as f:
            analysis = json.load(f)

        events = repo.list_events(ctx.conn, ctx.job_id)
        style = load_style("youtube")  # default, could come from job config
        target_seconds = ctx.settings.pipeline.review.target_duration_minutes * 60

        outline = plan_review(events, style, target_seconds=target_seconds)

        return write_script(
            outline,
            analysis,
            style,
            target_seconds * 150 // 60,
            StageContext(
                job_id=ctx.job_id,
                jobs_dir=ctx.jobs_dir,
                conn=ctx.conn,
                manager=ctx.manager,
                cache=ctx.cache,
                settings=ctx.settings,
            ),
            model=ctx.settings.models.reasoning.model,
        )

    def tts_chunks_fn(ctx: PipelineContext) -> Any:
        from movie_review.domain import ReviewScript
        from movie_review.tts.chunks import (
            DEFAULT_VOICE,
            plan_chunks,
            synthesize_chunks,
        )
        from movie_review.tts.factory import build_tts_adapter

        script_path = Path(ctx.jobs_dir) / ctx.job_id / "review" / "review-script.json"
        import json

        with script_path.open() as f:
            script_data = json.load(f)

        script = ReviewScript.model_validate(script_data["script"])

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
        from movie_review.domain import ReviewScript
        from movie_review.tts.chunks import (
            DEFAULT_VOICE,
            collect_chunk_results,
            plan_chunks,
        )
        from movie_review.tts.concat import NARRATION_FILENAME, concatenate

        script_path = Path(ctx.jobs_dir) / ctx.job_id / "review" / "review-script.json"
        import json

        with script_path.open() as f:
            script_data = json.load(f)

        script = ReviewScript.model_validate(script_data["script"])

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
        from movie_review.domain import ReviewScript
        from movie_review.tts.reconcile import run_reconciliation

        script_path = Path(ctx.jobs_dir) / ctx.job_id / "review" / "review-script.json"
        import json

        with script_path.open() as f:
            script_data = json.load(f)

        script = ReviewScript.model_validate(script_data["script"])
        narration_path = Path(ctx.jobs_dir) / ctx.job_id / "tts" / "narration.wav"
        target_seconds = ctx.settings.pipeline.review.target_duration_minutes * 60
        wpm = ctx.settings.pipeline.review.target_wpm

        return run_reconciliation(
            script,
            narration_path,
            target_seconds,
            wpm,
            StageContext(
                job_id=ctx.job_id,
                jobs_dir=ctx.jobs_dir,
                conn=ctx.conn,
                manager=ctx.manager,
                cache=ctx.cache,
                settings=ctx.settings,
            ),
        )

    def render_manifest_fn(ctx: PipelineContext) -> Any:
        from movie_review.domain import ReviewScript
        from movie_review.rendering.clips import select_clips
        from movie_review.rendering.manifest import assemble_manifest
        from movie_review.rendering.planner import plan_visuals
        from movie_review.storage import repositories as repo

        script_path = ctx.jobs_dir / ctx.job_id / "review" / "review-script.json"
        import json

        with script_path.open() as f:
            script_data = json.load(f)

        script = ReviewScript.model_validate(script_data["script"])
        scenes = repo.list_scenes(ctx.conn, ctx.job_id)
        paragraphs = [p for s in script.sections for p in s.paragraphs]

        analyses = {a.scene_id: a for a in repo.list_scene_analyses(ctx.conn, ctx.job_id)}

        events = repo.list_events(ctx.conn, ctx.job_id)

        # Plan visuals
        visual_plan = plan_visuals(script, scenes, analyses, events)

        # Need narration timings - simplified for now
        narration_seconds = {p.id: 10.0 for p in paragraphs}

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

    def render_fn(ctx: PipelineContext) -> Any:
        from movie_review.domain import RenderManifest
        from movie_review.rendering.renderer import render_job

        manifest_path = Path(ctx.jobs_dir) / ctx.job_id / "render" / "render-manifest.json"
        import json

        with manifest_path.open() as f:
            manifest_data = json.load(f)

        manifest = RenderManifest.model_validate(manifest_data["manifest"])

        source_movie = ctx.movie_path
        narration_wav = Path(ctx.jobs_dir) / ctx.job_id / "tts" / "narration.wav"
        subtitles_srt = Path(ctx.jobs_dir) / ctx.job_id / "render" / "review.srt"

        return render_job(
            manifest,
            source_movie,
            narration_wav,
            subtitles_srt if subtitles_srt.is_file() else None,
            ctx,
        )

    def quality_fn(ctx: PipelineContext) -> Any:
        from movie_review.domain import QualityMetric
        from movie_review.quality.gates import run_quality_gate

        # Build metrics
        metrics: list[QualityMetric] = []
        # ... compute metrics from artifacts

        target_seconds = ctx.settings.pipeline.review.target_duration_minutes * 60
        actual_seconds = target_seconds  # would measure actual

        return run_quality_gate(metrics, actual_seconds, target_seconds, ctx)

    return {
        "ingest": ingest_fn,
        "scenes": scenes_fn,
        "transcript": transcript_fn,
        "vision": vision_fn,
        "characters": characters_fn,
        "locations": locations_fn,
        "events": events_fn,
        "arcs": arcs_fn,
        "themes": themes_fn,
        "twists": twists_fn,
        "story": story_fn,
        "review": review_fn,
        "tts-chunks": tts_chunks_fn,
        "tts-concat": tts_concat_fn,
        "tts-reconcile": tts_reconcile_fn,
        "render-manifest": render_manifest_fn,
        "render": render_fn,
        "quality": quality_fn,
    }.get(stage_name)


def resume_job(
    job_id: str,
    db_path: str | None = None,
    on_progress: Callable[[str, StageResult | None], None] | None = None,
    profile: str | None = None,
    on_work: Callable[[str, WorkProgress], None] | None = None,
) -> list[StageResult]:
    """Resume a job from its recovery point.

    ``on_progress`` is forwarded to :func:`run_pipeline`; see there.
    ``on_work`` likewise receives in-stage steps.
    ``profile`` selects a ``models.yaml`` profile for this resume only.
    """
    from movie_review.config.settings import load_settings
    from movie_review.storage.database import bootstrap

    settings = load_settings()
    resolved_db = Path(db_path) if db_path else Path(settings.paths.data_dir) / "jobs.db"
    conn = sqlite3.connect(str(bootstrap(resolved_db)))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    manager = JobManager(conn)

    plan = recovery_plan(manager, job_id)
    if plan.resume_stage in ("done", "manual"):
        return [
            StageResult(stage=plan.resume_stage, success=True, duration_ms=0, error=plan.reason)
        ]

    # Get the movie path from the job
    job = manager.get(job_id)
    return run_pipeline(
        job_id,
        job.input_file,
        db_path,
        start_stage=plan.resume_stage,
        on_progress=on_progress,
        profile=profile,
        on_work=on_work,
    )


def validate_job(job_id: str, db_path: str | None = None) -> bool:
    """Validate a job record and its artifacts."""
    from movie_review.config.settings import load_settings
    from movie_review.storage.database import bootstrap

    settings = load_settings()
    resolved_db = Path(db_path) if db_path else Path(settings.paths.data_dir) / "jobs.db"
    conn = sqlite3.connect(str(bootstrap(resolved_db)))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    manager = JobManager(conn)

    job = manager.get(job_id)

    # Run integrity check
    from movie_review.artifacts import scan_job_integrity

    # Build artifact records based on job status
    records = _build_artifact_records(job, settings.paths.data_dir)
    report = scan_job_integrity(settings.paths.data_dir, job_id, records)

    return report.passed


def _build_artifact_records(job: Any, jobs_dir: str) -> list[ArtifactRecord]:
    """Build artifact records for integrity check based on job status."""
    from movie_review.artifacts import ArtifactRecord
    from movie_review.domain import JobStatus

    records: list[ArtifactRecord] = []

    # Map job status to expected artifacts
    if job.status in (
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
        JobStatus.VISUAL_ANALYSIS_READY,
        JobStatus.CHARACTERS_READY,
        JobStatus.EVENTS_READY,
        JobStatus.STORY_READY,
        JobStatus.REVIEW_PLAN_READY,
        JobStatus.SCRIPT_READY,
        JobStatus.SCRIPT_VERIFIED,
        JobStatus.AUDIO_READY,
        JobStatus.EDIT_PLAN_READY,
        JobStatus.RENDERED,
        JobStatus.QUALITY_CHECKED,
        JobStatus.COMPLETED,
    ):
        records.append(ArtifactRecord(stage="media", filename="media.json", expected_hash=""))
        records.append(ArtifactRecord(stage="scenes", filename="scenes.json", expected_hash=""))
        records.append(
            ArtifactRecord(stage="transcript", filename="transcript.json", expected_hash="")
        )

    # Add more based on status...
    return records
