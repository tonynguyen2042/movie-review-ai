"""Scene detection stage: cuts → stable scenes → ``scenes.json`` (T014, FR-002).

Follows the pipeline stage contract with the T011 lifecycle pattern, moving
``MEDIA_READY`` → ``SCENES_READY``. Detection runs on the analysis proxy when
present (T012), else the source file. Detection metadata beyond timestamps
(shot counts, motion, brightness) stays at domain defaults until frame and
vision stages enrich it (T015/T025).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.domain import Artifact, JobStatus, Scene
from movie_review.jobs.failure import job_failure_message
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.media import scenes as adapter
from movie_review.media.scenes import DetectionResult
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "scenes"
STAGE_VERSION = "v1"
SCENES_FILENAME = "scenes.json"
PROXY_FILENAME = "proxy.mp4"


class SceneStageError(Exception):
    """Scene detection stage failed in a classified way."""


@dataclass
class ScenesResult:
    """Outcome of one scene detection run."""

    scenes: list[Scene]
    scenes_path: Path
    analyzed_file: Path
    cache_hit: bool
    duration_ms: int


def resolve_analysis_file(
    source: str | Path, *, jobs_dir: str | Path, job_id: str, prefer_proxy: bool = False
) -> Path:
    """The file the scene boundaries are read from.

    The proxy is only used when a caller asks for it. Preferring it by
    default made the stage non-idempotent: the proxy is built in the vision
    stage, which runs *after* this one, so the first run detected on the
    source and any later run detected on the proxy. The analysed file is
    part of the cache key, so the second run missed the cache and produced a
    different set of cuts for the same movie.

    The source is also the honest input: the proxy is a re-encode, so cuts
    found on it are cuts found on a different picture.
    """
    if prefer_proxy:
        proxy = artifacts.artifact_path(jobs_dir, job_id, "media", PROXY_FILENAME)
        if proxy.is_file():
            return proxy
    return Path(source)


def detect_scenes_stage(
    source: str | Path,
    ctx: StageContext,
    prefer_proxy: bool = False,
    detect_fn: Callable[..., DetectionResult] | None = None,
) -> ScenesResult:
    """Detect scenes for ``ctx.job_id`` through to ``SCENES_READY``."""
    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise SceneStageError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise SceneStageError(job_failure_message(job))

    analyzed = resolve_analysis_file(
        source, jobs_dir=ctx.jobs_dir, job_id=ctx.job_id, prefer_proxy=prefer_proxy
    )
    if not analyzed.is_file():
        raise SceneStageError(f"Input file not found: {analyzed}")

    # T006 has no in-progress scene state: MEDIA_READY jobs run then advance to
    # SCENES_READY; jobs already past it only refresh artifacts.
    owns_completion = job.status is JobStatus.MEDIA_READY

    detection = ctx.settings.pipeline.scene_detection
    file_hash = artifacts.sha256_file(analyzed)
    spec = CacheSpec(
        stage=STAGE_NAME,
        stage_version=STAGE_VERSION,
        input_hash=file_hash,
        generation_config={
            "detector": detection.detector,
            "threshold": detection.threshold,
            "min_scene_len": detection.min_scene_len,
        },
    )
    key = cache_key(spec)
    cached = ctx.cache.lookup_json(key)
    if cached is not None:
        try:
            scenes = [Scene.model_validate(item) for item in cached["scenes"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise SceneStageError(f"Cached scenes.json is corrupt for {analyzed}") from exc
        cache_hit = True
    else:
        try:
            result = (detect_fn or adapter.detect_scenes)(
                analyzed,
                detector=detection.detector,
                threshold=detection.threshold,
                min_scene_len=detection.min_scene_len,
            )
        except adapter.SceneDetectionError as exc:
            if owns_completion:
                ctx.manager.fail(ctx.job_id, STAGE_NAME, str(exc))
            raise SceneStageError(f"Cannot detect scenes in {analyzed}: {exc}") from exc
        scenes = [
            Scene(
                scene_id=f"scene_{index:06d}",
                start=cut.start,
                end=cut.end,
                duration=cut.end - cut.start,
            )
            for index, cut in enumerate(result.cuts, start=1)
        ]
        cache_hit = False

    # The scene list for a job is the whole set. Writing the new rows over
    # the old ones leaves any scene the new detection does not contain still
    # in the table with its old boundaries, so a re-run left a mix of two
    # timelines and the timeline consistency metric compared events against
    # a mixture.
    repo.delete_scenes(ctx.conn, ctx.job_id)
    for scene in scenes:
        repo.save_scene(ctx.conn, ctx.job_id, scene)
    document = {
        "job_id": ctx.job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "analyzed_file": str(analyzed),
        "scenes": [scene.model_dump(mode="json") for scene in scenes],
    }
    scenes_path = artifacts.artifact_path(ctx.jobs_dir, ctx.job_id, STAGE_NAME, SCENES_FILENAME)
    output_hash = artifacts.write_json(scenes_path, document)
    if not cache_hit:
        ctx.cache.store_json(key, document)
    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-scenes",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(ctx.jobs_dir, ctx.job_id, scenes_path),
            input_hash=file_hash,
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
            scenes=len(scenes),
        )
    if owns_completion:
        ctx.manager.transition(ctx.job_id, JobStatus.SCENES_READY)
    return ScenesResult(
        scenes=scenes,
        scenes_path=scenes_path,
        analyzed_file=analyzed,
        cache_hit=cache_hit,
        duration_ms=duration_ms,
    )
