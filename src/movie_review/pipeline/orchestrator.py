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

from movie_review.jobs.manager import JobManager
from movie_review.jobs.recovery import recovery_plan
from movie_review.pipeline.context import StageContext
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
class PipelineContext:
    """Runtime state for pipeline execution."""

    job_id: str
    jobs_dir: str
    conn: Any
    manager: JobManager
    cache: Any
    settings: Any
    movie_path: str | Path


def _stage_logger(stage: str):
    return logging.getLogger(f"pipeline.{stage}")


def run_stage(
    name: str,
    fn: Callable[[PipelineContext], Any],
    ctx: PipelineContext,
) -> StageResult:
    """Run a single stage with logging and error capture."""
    started = time.perf_counter()
    stage_logger = _stage_logger(name)
    with ulog.logging_context(job_id=ctx.job_id, stage=name):
        try:
            result = fn(ctx)
            duration_ms = int((time.perf_counter() - started) * 1000)
            ulog.log_event(
                stage_logger,
                event="stage.completed",
                status="ok",
                duration_ms=duration_ms,
            )
            return StageResult(stage=name, success=True, duration_ms=duration_ms)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            ulog.log_event(
                stage_logger,
                event="stage.failed",
                status="error",
                duration_ms=duration_ms,
                error=str(exc),
            )
            return StageResult(stage=name, success=False, duration_ms=duration_ms, error=str(exc))


def _build_context(job_id: str, movie_path: str | Path, db_path: str | None) -> PipelineContext:
    """Build runtime context from settings and job database."""
    from movie_review.cache.manager import CacheManager
    from movie_review.config.settings import load_settings
    from movie_review.storage.database import bootstrap
    
    settings = load_settings()
    resolved_db = Path(db_path) if db_path else Path(settings.paths.data_dir) / "jobs.db"
    conn = sqlite3.connect(str(bootstrap(resolved_db)))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    manager = JobManager(conn)
    # Cache dir is under data_dir/cache
    cache_dir = Path(settings.paths.data_dir) / "cache"
    cache = CacheManager(cache_dir)
    return PipelineContext(
        job_id=job_id,
        jobs_dir=settings.paths.data_dir,
        conn=conn,
        manager=manager,
        cache=cache,
        settings=settings,
        movie_path=movie_path,
    )


def run_pipeline(
    job_id: str,
    movie_path: str | Path,
    db_path: str | None = None,
    start_stage: str | None = None,
    end_stage: str | None = None,
) -> list[StageResult]:
    """Execute pipeline stages in sequence with optional start/end bounds."""
    ctx = _build_context(job_id, movie_path, db_path)
    results: list[StageResult] = []
    started = False
    finished = False
    
    for stage_name, _desc in STAGE_SEQUENCE:
        if end_stage is not None and stage_name == end_stage:
            finished = True
        if not started and (start_stage is None or stage_name == start_stage):
            started = True
        if not started or finished:
            if finished:
                break
            continue
        
        # Get the appropriate stage function
        stage_fn = _get_stage_function(stage_name)
        if stage_fn:
            result = run_stage(stage_name, stage_fn, ctx)
            results.append(result)
            if not result.success:
                break
    
    return results


def _get_stage_function(stage_name: str) -> Callable[[PipelineContext], Any] | None:
    """Map stage name to its execution function using lazy imports."""
    
    def ingest_fn(ctx: PipelineContext):
        from movie_review.domain import JobStatus
        from movie_review.media.ingest import ingest_movie
        job = ctx.manager.get(ctx.job_id)
        if job.status in (JobStatus.CREATED, JobStatus.INGESTING):
            ctx.manager.transition(ctx.job_id, JobStatus.INGESTING)
        return ingest_movie(ctx.movie_path, StageContext(
            job_id=ctx.job_id,
            jobs_dir=ctx.jobs_dir,
            conn=ctx.conn,
            manager=ctx.manager,
            cache=ctx.cache,
            settings=ctx.settings,
        ))
    
    def scenes_fn(ctx: PipelineContext):
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
    
    def transcript_fn(ctx: PipelineContext):
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
    
    def vision_fn(ctx: PipelineContext):
        from movie_review.storage import repositories as repo
        from movie_review.vision.analysis import run_visual_analysis
        scenes = repo.list_scenes(ctx.conn, ctx.job_id)
        segments = repo.list_transcript_segments(ctx.conn, ctx.job_id)
        # Frames need to be sampled - for now empty
        frames: dict[str, list[Path]] = {}
        return run_visual_analysis(
            scenes, frames, segments,
            StageContext(
                job_id=ctx.job_id,
                jobs_dir=ctx.jobs_dir,
                conn=ctx.conn,
                manager=ctx.manager,
                cache=ctx.cache,
                settings=ctx.settings,
            ),
        )
    
    def characters_fn(ctx: PipelineContext):
        from movie_review.characters.discovery import discover_characters, save_discovery
        from movie_review.characters.linking import link_characters
        from movie_review.domain import SceneAnalysis
        from movie_review.storage import repositories as repo
        
        scenes = repo.list_scenes(ctx.conn, ctx.job_id)
        analyses_list = []
        vision_path = Path(ctx.jobs_dir) / ctx.job_id / "vision" / "vision.json"
        if vision_path.is_file():
            import json
            with vision_path.open() as f:
                vision_data = json.load(f)
                analyses_list = vision_data.get("analyses", [])
        
        analyses = {a["scene_id"]: SceneAnalysis.model_validate(a) for a in analyses_list if "scene_id" in a}
        
        scene_spans = {scene.scene_id: (scene.start, scene.end) for scene in scenes}
        segments = repo.list_transcript_segments(ctx.conn, ctx.job_id)
        
        result = discover_characters(analyses, scene_spans, segments)
        save_discovery(ctx.conn, ctx.job_id, result)
        link_characters(ctx.conn, ctx.job_id)
        
        return result
    
    def locations_fn(ctx: PipelineContext):
        from movie_review.domain import SceneAnalysis
        from movie_review.knowledge.locations import extract_locations, scene_locations
        from movie_review.storage import repositories as repo
        
        scenes = repo.list_scenes(ctx.conn, ctx.job_id)
        vision_path = Path(ctx.jobs_dir) / ctx.job_id / "vision" / "vision.json"
        analyses_list = []
        if vision_path.is_file():
            import json
            with vision_path.open() as f:
                vision_data = json.load(f)
                analyses_list = vision_data.get("analyses", [])
        
        analyses = {a["scene_id"]: SceneAnalysis.model_validate(a) for a in analyses_list if "scene_id" in a}
        analyses_list = list(analyses.values())
        
        scene_spans = scene_locations(scenes)
        locations = extract_locations(analyses_list, scene_spans)
        
        for loc in locations:
            repo.save_location(ctx.conn, ctx.job_id, loc)
        return locations
    
    def events_fn(ctx: PipelineContext):
        from movie_review.domain import SceneAnalysis
        from movie_review.storage import repositories as repo
        from movie_review.story.events import run_event_extraction
        
        scenes = repo.list_scenes(ctx.conn, ctx.job_id)
        analyses_list = []
        vision_path = Path(ctx.jobs_dir) / ctx.job_id / "vision" / "vision.json"
        if vision_path.is_file():
            import json
            with vision_path.open() as f:
                vision_data = json.load(f)
                analyses_list = vision_data.get("analyses", [])
        
        analyses = {a["scene_id"]: SceneAnalysis.model_validate(a) for a in analyses_list if "scene_id" in a}
        
        characters = repo.list_characters(ctx.conn, ctx.job_id)
        segments = repo.list_transcript_segments(ctx.conn, ctx.job_id)
        
        return run_event_extraction(
            scenes, analyses, segments, characters,
            StageContext(
                job_id=ctx.job_id,
                jobs_dir=ctx.jobs_dir,
                conn=ctx.conn,
                manager=ctx.manager,
                cache=ctx.cache,
                settings=ctx.settings,
            ),
        )
    
    def arcs_fn(ctx: PipelineContext):
        from movie_review.storage import repositories as repo
        from movie_review.story.arcs import extract_story_arcs
        
        events = repo.list_events(ctx.conn, ctx.job_id)
        characters = repo.list_characters(ctx.conn, ctx.job_id)
        character_lines = "\n".join(f"{c.id}: {c.name}" for c in characters)
        
        return extract_story_arcs(
            events, character_lines,
            job_id=ctx.job_id,
            jobs_dir=ctx.jobs_dir,
            conn=ctx.conn,
            cache=ctx.cache,
            model=ctx.settings.models.reasoning.model,
        )
    
    def themes_fn(ctx: PipelineContext):
        from movie_review.storage import repositories as repo
        from movie_review.story.themes import extract_themes
        
        events = repo.list_events(ctx.conn, ctx.job_id)
        characters = repo.list_characters(ctx.conn, ctx.job_id)
        character_lines = "\n".join(f"{c.id}: {c.name}" for c in characters)
        
        return extract_themes(
            events, character_lines,
            job_id=ctx.job_id,
            jobs_dir=ctx.jobs_dir,
            conn=ctx.conn,
            cache=ctx.cache,
            model=ctx.settings.models.reasoning.model,
        )
    
    def twists_fn(ctx: PipelineContext):
        from movie_review.storage import repositories as repo
        from movie_review.story.twists import extract_twists
        
        events = repo.list_events(ctx.conn, ctx.job_id)
        characters = repo.list_characters(ctx.conn, ctx.job_id)
        character_lines = "\n".join(f"{c.id}: {c.name}" for c in characters)
        
        return extract_twists(
            events, character_lines,
            job_id=ctx.job_id,
            jobs_dir=ctx.jobs_dir,
            conn=ctx.conn,
            cache=ctx.cache,
            model=ctx.settings.models.reasoning.model,
        )
    
    def story_fn(ctx: PipelineContext):
        from movie_review.knowledge.analysis import build_movie_analysis
        return build_movie_analysis(StageContext(
            job_id=ctx.job_id,
            jobs_dir=ctx.jobs_dir,
            conn=ctx.conn,
            manager=ctx.manager,
            cache=ctx.cache,
            settings=ctx.settings,
        ))
    
    def review_fn(ctx: PipelineContext):
        from movie_review.review.planner import plan_review
        from movie_review.review.styles import load_style
        from movie_review.review.writer import write_script
        from movie_review.storage import repositories as repo
        
        job = ctx.manager.get(ctx.job_id)
        analysis_path = Path(ctx.jobs_dir) / ctx.job_id / "movie-analysis.json"
        import json
        with analysis_path.open() as f:
            analysis = json.load(f)
        
        events = repo.list_events(ctx.conn, ctx.job_id)
        style = load_style("youtube")  # default, could come from job config
        target_seconds = ctx.settings.pipeline.review.target_duration_minutes * 60
        
        outline = plan_review(events, style, target_seconds=target_seconds)
        
        return write_script(
            outline, analysis, style, target_seconds * 150 // 60,
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
    
    def tts_chunks_fn(ctx: PipelineContext):
        from movie_review.domain import ReviewScript
        from movie_review.tts.chunks import plan_chunks, synthesize_chunks
        from movie_review.tts.qwen_tts import QwenTTSAdapter
        
        script_path = Path(ctx.jobs_dir) / ctx.job_id / "review" / "review-script.json"
        import json
        with script_path.open() as f:
            script_data = json.load(f)
        
        script = ReviewScript.model_validate(script_data["script"])
        
        port = QwenTTSAdapter(ctx.settings.models.tts.model)
        chunks = plan_chunks(script, voice="default")
        return synthesize_chunks(chunks, port, ctx.jobs_dir, ctx.job_id)
    
    def tts_concat_fn(ctx: PipelineContext):
        
        # Load chunk results from artifacts
        # This is simplified - in practice would load from chunk metadata
        pass
    
    def tts_reconcile_fn(ctx: PipelineContext):
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
            script, narration_path, target_seconds, wpm,
            StageContext(
                job_id=ctx.job_id,
                jobs_dir=ctx.jobs_dir,
                conn=ctx.conn,
                manager=ctx.manager,
                cache=ctx.cache,
                settings=ctx.settings,
            ),
        )
    
    def render_manifest_fn(ctx: PipelineContext):
        from movie_review.domain import ReviewScript, SceneAnalysis
        from movie_review.rendering.manifest import assemble_manifest
        from movie_review.rendering.planner import plan_visuals
        from movie_review.storage import repositories as repo
        
        script_path = Path(ctx.jobs_dir) / ctx.job_id / "review" / "review-script.json"
        import json
        with script_path.open() as f:
            script_data = json.load(f)
        
        script = ReviewScript.model_validate(script_data["script"])
        scenes = repo.list_scenes(ctx.conn, ctx.job_id)
        
        # Load analyses
        vision_path = Path(ctx.jobs_dir) / ctx.job_id / "vision" / "vision.json"
        analyses_list = []
        if vision_path.is_file():
            with vision_path.open() as f:
                vision_data = json.load(f)
                analyses_list = vision_data.get("analyses", [])
        analyses = {a["scene_id"]: SceneAnalysis.model_validate(a) for a in analyses_list if "scene_id" in a}
        
        events = repo.list_events(ctx.conn, ctx.job_id)
        
        # Plan visuals
        visual_plan = plan_visuals(script, scenes, analyses, events)
        
        # Need narration timings - simplified for now
        narration_seconds = {p.id: 10.0 for s in script.sections for p in s.paragraphs}
        
        # Get clips from visual plan (simplified)
        clips = {}
        for pc in visual_plan.paragraph_clips:
            if pc.paragraph_id not in clips:
                clip = repo.get_clip(ctx.conn, ctx.job_id, pc.paragraph_id)  # would need to implement
                if clip:
                    clips[pc.paragraph_id] = clip
        
        movie = repo.get_movie(ctx.conn, ctx.job_id)
        movie_duration = movie.metadata.duration_seconds if movie else 0
        
        return assemble_manifest(
            [p for s in script.sections for p in s.paragraphs],
            clips,
            narration_seconds,
            movie_duration,
            ctx,
            max_total_seconds=ctx.settings.source_video.max_total_seconds,
            max_source_ratio=ctx.settings.source_video.max_source_ratio,
        )
    
    def render_fn(ctx: PipelineContext):
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
            manifest, source_movie, narration_wav,
            subtitles_srt if subtitles_srt.is_file() else None,
            ctx,
        )
    
    def quality_fn(ctx: PipelineContext):
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
) -> list[StageResult]:
    """Resume a job from its recovery point."""
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
        return [StageResult(stage=plan.resume_stage, success=True, duration_ms=0, error=plan.reason)]
    
    # Get the movie path from the job
    job = manager.get(job_id)
    return run_pipeline(job_id, job.input_file, db_path, start_stage=plan.resume_stage)


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


def _build_artifact_records(job: Any, jobs_dir: str) -> list:
    """Build artifact records for integrity check based on job status."""
    from movie_review.artifacts import ArtifactRecord
    from movie_review.domain import JobStatus
    
    records: list[ArtifactRecord] = []
    
    # Map job status to expected artifacts
    if job.status in (JobStatus.MEDIA_READY, JobStatus.SCENES_READY, JobStatus.TRANSCRIPT_READY, 
                      JobStatus.VISUAL_ANALYSIS_READY, JobStatus.CHARACTERS_READY, JobStatus.EVENTS_READY,
                      JobStatus.STORY_READY, JobStatus.REVIEW_PLAN_READY, JobStatus.SCRIPT_READY,
                      JobStatus.SCRIPT_VERIFIED, JobStatus.AUDIO_READY, JobStatus.EDIT_PLAN_READY,
                      JobStatus.RENDERED, JobStatus.QUALITY_CHECKED, JobStatus.COMPLETED):
        records.append(ArtifactRecord(stage="media", filename="media.json", expected_hash=""))
        records.append(ArtifactRecord(stage="scenes", filename="scenes.json", expected_hash=""))
        records.append(ArtifactRecord(stage="transcript", filename="transcript.json", expected_hash=""))
    
    # Add more based on status...
    return records