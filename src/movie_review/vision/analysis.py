"""Scene visual analysis stage: frames + dialogue → VLM → ``vision.json`` (T025).

Follows the pipeline stage contract with the T011 lifecycle pattern, moving
``TRANSCRIPT_READY`` → ``VISUAL_ANALYSIS_READY``. Each scene is analyzed
independently with a small context window (its frames, overlapping dialogue,
previous scene summary) per P3. Per-scene caching makes reruns cheap. The VLM
is chosen by :func:`build_vlm_adapter` from the configured ``ModelSpec`` --
local MLX weights, or a remote OpenAI-compatible endpoint.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.config.prompts import load_prompt, render
from movie_review.domain import Artifact, JobStatus, Scene, SceneAnalysis, TranscriptSegment
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog
from movie_review.vision.factory import build_vlm_adapter
from movie_review.vision.port import AnalysisInput, VLMPort

_logger = logging.getLogger(__name__)

STAGE_NAME = "vision"
STAGE_VERSION = "v1"
VISION_FILENAME = "vision.json"
MAX_DIALOGUE_CHARS = 2000


class VisualAnalysisError(Exception):
    """Visual analysis stage failed in a classified way."""


@dataclass
class VisualAnalysisResult:
    """Outcome of one visual analysis run."""

    analyses: list[SceneAnalysis]
    vision_path: Path
    cache_hits: int
    duration_ms: int


def scene_dialogue(segments: list[TranscriptSegment], start: float, end: float) -> str:
    """Join segment texts overlapping ``[start, end)``, truncated for prompts."""
    texts = [segment.text for segment in segments if segment.start < end and segment.end > start]
    joined = " ".join(text for text in texts if text.strip())
    if len(joined) > MAX_DIALOGUE_CHARS:
        return joined[:MAX_DIALOGUE_CHARS] + "…"
    return joined


def previous_summary(analysis: SceneAnalysis | None) -> str:
    """One-line prior-scene context for the next prompt."""
    if analysis is None:
        return "none (first scene)"
    actions = "; ".join(analysis.actions[:3])
    return f"{analysis.location}: {actions}" if actions else analysis.location or "nothing notable"


def run_visual_analysis(
    scenes: list[Scene],
    frames: dict[str, list[Path]],
    segments: list[TranscriptSegment],
    ctx: StageContext,
    port: VLMPort | None = None,
    prompt_version: str | None = None,
) -> VisualAnalysisResult:
    """Analyze scenes for ``ctx.job_id`` through to ``VISUAL_ANALYSIS_READY``."""
    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise VisualAnalysisError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise VisualAnalysisError(f"Job {ctx.job_id} failed; resume arrives in T085")
    owns_completion = job.status is JobStatus.TRANSCRIPT_READY

    prompt = load_prompt("scene_analysis", prompt_version)
    # build_vlm_adapter honours ModelSpec.backend, so a remote VLM is reachable
    # without MLX installed. Hardcoding QwenVLAdapter ignored the configuration.
    active = port or build_vlm_adapter(ctx.settings.models.vision)
    # From the port, not the adapter type: a remote adapter's real model id must
    # reach the cache key, otherwise every remote run keys on the class name.
    model = active.model

    analyses: list[SceneAnalysis] = []
    cache_hits = 0
    previous: SceneAnalysis | None = None
    try:
        for scene in scenes:
            scene_frames = frames.get(scene.scene_id, [])
            if not scene_frames:
                raise VisualAnalysisError(f"No frames for {scene.scene_id}")
            dialogue = scene_dialogue(segments, scene.start, scene.end)
            summary = previous_summary(previous)
            text = render(
                prompt,
                scene_id=scene.scene_id,
                frame_count=str(len(scene_frames)),
                metadata=f"{scene.duration:.1f}s, {len(scene_frames)} frames",
                dialogue=dialogue or "(no dialogue)",
                previous_summary=summary,
            )
            spec = CacheSpec(
                stage=STAGE_NAME,
                stage_version=STAGE_VERSION,
                input_hash=_scene_input_hash(scene, scene_frames, dialogue, summary),
                model_id=model,
                prompt_version=f"{prompt.name}:{prompt.version}",
            )
            key = cache_key(spec)
            cached = ctx.cache.lookup_json(key)
            if cached is not None:
                try:
                    analysis = SceneAnalysis.model_validate(cached["analysis"])
                except (KeyError, TypeError, ValueError) as exc:
                    if owns_completion:
                        ctx.manager.fail(ctx.job_id, STAGE_NAME, f"cached vision corrupt: {exc}")
                    raise VisualAnalysisError(
                        f"Cached vision is corrupt for {scene.scene_id}"
                    ) from exc
                cache_hits += 1
            else:
                try:
                    analysis = active.analyze(
                        AnalysisInput(
                            scene_id=scene.scene_id,
                            frames=scene_frames,
                            dialogue=dialogue,
                            previous_summary=None if previous is None else summary,
                        ),
                        text,
                    )
                except Exception as exc:
                    if owns_completion:
                        ctx.manager.fail(ctx.job_id, STAGE_NAME, f"{scene.scene_id}: {exc}")
                    raise VisualAnalysisError(f"Cannot analyze {scene.scene_id}: {exc}") from exc
                ctx.cache.store_json(key, {"analysis": analysis.model_dump(mode="json")})
            if analysis.scene_id != scene.scene_id:
                raise VisualAnalysisError(f"Scene ID drift in analysis for {scene.scene_id}")
            analyses.append(analysis)
            previous = analysis
    finally:
        active.unload()

    document = {
        "job_id": ctx.job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "prompt": f"{prompt.name}:{prompt.version}",
        "model": model,
        "analyses": [analysis.model_dump(mode="json") for analysis in analyses],
    }
    vision_path = artifacts.artifact_path(ctx.jobs_dir, ctx.job_id, STAGE_NAME, VISION_FILENAME)
    output_hash = artifacts.write_json(vision_path, document)
    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-vision",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            input_hash=_run_input_hash(scenes),
            output_hash=output_hash,
            model=model,
            prompt_version=f"{prompt.name}:{prompt.version}",
        ),
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    with ulog.logging_context(job_id=ctx.job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="stage.completed",
            status="ok",
            duration_ms=duration_ms,
            cache_hits=cache_hits,
            scenes=len(analyses),
        )
    if owns_completion:
        ctx.manager.transition(ctx.job_id, JobStatus.VISUAL_ANALYSIS_READY)
    return VisualAnalysisResult(
        analyses=analyses,
        vision_path=vision_path,
        cache_hits=cache_hits,
        duration_ms=duration_ms,
    )


def _scene_input_hash(scene: Scene, scene_frames: list[Path], dialogue: str, summary: str) -> str:
    parts = [scene.scene_id, f"{scene.start:.3f}", f"{scene.end:.3f}", dialogue, summary]
    for frame in scene_frames:
        parts.append(artifacts.sha256_file(frame))
    return artifacts.sha256_bytes("|".join(parts).encode("utf-8"))


def _run_input_hash(scenes: list[Scene]) -> str:
    return artifacts.sha256_bytes(
        "|".join(f"{scene.scene_id}:{scene.start:.3f}:{scene.end:.3f}" for scene in scenes).encode(
            "utf-8"
        )
    )
