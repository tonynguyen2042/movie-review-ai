"""Render manifest assembly: narration + clips → timeline (T058, spec 44).

Sequential segments pair each paragraph's narration duration with its clip
(looping short clips when needed). Source-footage totals are enforced
against the configured product controls — over-limit manifests fail loudly
instead of silently trimming content.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.domain import (
    Artifact,
    JobStatus,
    ManifestSegment,
    RenderManifest,
    ReviewParagraph,
)
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.context import StageContext
from movie_review.rendering.clips import SelectedClip
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "render"
STAGE_VERSION = "v1"
MANIFEST_FILENAME = "render-manifest.json"


class ManifestError(Exception):
    """Manifest assembly failed in a classified way."""


@dataclass(frozen=True)
class ManifestResult:
    """Assembled manifest with totals."""

    manifest: RenderManifest
    manifest_path: Path
    cache_hit: bool
    duration_ms: int


def build_manifest(
    paragraphs: list[ReviewParagraph],
    clips: dict[str, SelectedClip],
    narration_seconds: dict[str, float],
    movie_duration_seconds: float,
    max_total_seconds: float,
    max_source_ratio: float,
) -> RenderManifest:
    """Assemble sequential segments; raises :class:`ManifestError` on limits."""
    if movie_duration_seconds <= 0:
        raise ManifestError(f"Invalid movie duration: {movie_duration_seconds}")
    segments: list[ManifestSegment] = []
    cursor = 0.0
    for paragraph in paragraphs:
        clip = clips.get(paragraph.id)
        if clip is None:
            raise ManifestError(f"No clip for paragraph {paragraph.id}")
        duration = narration_seconds.get(paragraph.id)
        if duration is None or duration <= 0:
            raise ManifestError(f"No narration duration for {paragraph.id}")
        clip_span = clip.end - clip.start
        segments.append(
            ManifestSegment(
                paragraph_id=paragraph.id,
                start=cursor,
                duration=duration,
                scene_id=clip.scene_id,
                clip_start=clip.start,
                clip_end=clip.end,
                loop_clip=duration > clip_span,
            )
        )
        cursor += duration
    source_seconds = sum(min(seg.duration, _clip_span(seg, clips)) for seg in segments)
    if source_seconds > max_total_seconds:
        raise ManifestError(
            f"Source footage {source_seconds:.1f}s exceeds limit {max_total_seconds:.1f}s"
        )
    ratio = source_seconds / movie_duration_seconds
    if ratio > max_source_ratio:
        raise ManifestError(f"Source ratio {ratio:.3f} exceeds limit {max_source_ratio}")
    return RenderManifest(segments=segments, total_seconds=cursor, source_seconds=source_seconds)


def _clip_span(segment: ManifestSegment, clips: dict[str, SelectedClip]) -> float:
    clip = clips[segment.paragraph_id]
    return clip.end - clip.start


def assemble_manifest(
    paragraphs: list[ReviewParagraph],
    clips: dict[str, SelectedClip],
    narration_seconds: dict[str, float],
    movie_duration_seconds: float,
    ctx: StageContext,
    max_total_seconds: float = 420.0,
    max_source_ratio: float = 0.35,
) -> ManifestResult:
    """Build, persist, and cache the render manifest through to EDIT_PLAN_READY."""
    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise ManifestError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise ManifestError(f"Job {ctx.job_id} failed; resume arrives in T085")
    owns_completion = job.status is JobStatus.AUDIO_READY

    try:
        manifest = build_manifest(
            paragraphs,
            clips,
            narration_seconds,
            movie_duration_seconds,
            max_total_seconds,
            max_source_ratio,
        )
    except ManifestError as exc:
        if owns_completion:
            ctx.manager.fail(ctx.job_id, STAGE_NAME, str(exc))
        raise
    key = cache_key(
        CacheSpec(
            stage=STAGE_NAME,
            stage_version=STAGE_VERSION,
            input_hash=artifacts.sha256_bytes(
                "|".join(f"{p.id}:{narration_seconds.get(p.id)}" for p in paragraphs).encode()
            ),
            generation_config={
                "max_total_seconds": max_total_seconds,
                "max_source_ratio": max_source_ratio,
            },
        )
    )
    cached = ctx.cache.lookup_json(key)
    manifest_path = artifacts.artifact_path(ctx.jobs_dir, ctx.job_id, STAGE_NAME, MANIFEST_FILENAME)
    if cached is not None:
        try:
            manifest = RenderManifest.model_validate(cached["manifest"])
            cache_hit = True
        except (KeyError, TypeError, ValueError) as exc:
            if owns_completion:
                ctx.manager.fail(ctx.job_id, STAGE_NAME, f"cached manifest corrupt: {exc}")
            raise ManifestError("Cached render manifest is corrupt") from exc
    else:
        cache_hit = False
        ctx.cache.store_json(key, {"manifest": manifest.model_dump(mode="json")})

    output_hash = artifacts.write_json(manifest_path, manifest.model_dump(mode="json"))
    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-render-manifest",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            input_hash=key,
            output_hash=output_hash,
        ),
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    with ulog.logging_context(job_id=ctx.job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="stage.completed",
            status="ok",
            duration_ms=duration_ms,
            cache_hit=cache_hit,
        )
    if owns_completion:
        ctx.manager.transition(ctx.job_id, JobStatus.EDIT_PLAN_READY)
    return ManifestResult(
        manifest=manifest,
        manifest_path=manifest_path,
        cache_hit=cache_hit,
        duration_ms=duration_ms,
    )
