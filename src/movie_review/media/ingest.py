"""Media ingest stage: validate → probe → persist ``media.json`` (T011, FR-001).

Follows the pipeline stage contract: validate input, check cache, execute,
validate output, persist artifact, record metrics, mark complete. Idempotent:
reruns replace the same rows, files, and cache entries.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.domain import Artifact, JobStatus, Movie, MovieMetadata
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.media import ffmpeg as ff
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "ingest"
STAGE_VERSION = "v1"
MEDIA_FILENAME = "media.json"


class IngestError(Exception):
    """Ingest failed in a classified way (bad input, unreadable media, state)."""


@dataclass
class IngestResult:
    """Outcome of one ingest run."""

    movie: Movie
    media_path: Path
    cache_hit: bool
    duration_ms: int


def ingest_movie(
    input_path: str | Path,
    ctx: StageContext,
    probe_fn: Callable[[str], MovieMetadata] = ff.probe,
) -> IngestResult:
    """Ingest one movie file for ``ctx.job_id`` through to ``MEDIA_READY``."""
    started = time.perf_counter()
    source = Path(input_path)
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise IngestError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise IngestError(f"Job {ctx.job_id} failed; resume arrives in T085")
    if not source.is_file():
        raise IngestError(f"Input file not found: {source}")

    if job.status is JobStatus.CREATED:
        ctx.manager.transition(ctx.job_id, JobStatus.INGESTING)
        initial = JobStatus.INGESTING
    else:
        initial = job.status

    file_hash = artifacts.sha256_file(source)
    spec = CacheSpec(stage=STAGE_NAME, stage_version=STAGE_VERSION, input_hash=file_hash)
    key = cache_key(spec)
    cached = ctx.cache.lookup_json(key)
    if cached is not None:
        try:
            metadata = Movie.model_validate(cached["movie"]).metadata
        except (KeyError, TypeError, ValueError) as exc:
            raise IngestError(f"Cached media.json is corrupt for {source}") from exc
        cache_hit = True
    else:
        try:
            metadata = probe_fn(str(source))
        except (ff.ProbeError, ff.ProcessError) as exc:
            if initial is JobStatus.INGESTING:
                ctx.manager.fail(ctx.job_id, STAGE_NAME, str(exc))
            raise IngestError(f"Cannot ingest {source}: {exc}") from exc
        cache_hit = False

    movie = Movie(id=f"movie-{ctx.job_id}", metadata=metadata)
    repo.save_movie(ctx.conn, ctx.job_id, movie)

    document = {
        "job_id": ctx.job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "movie": movie.model_dump(mode="json"),
    }
    media_path = artifacts.artifact_path(ctx.jobs_dir, ctx.job_id, "media", MEDIA_FILENAME)
    output_hash = artifacts.write_json(media_path, document)
    if not cache_hit:
        ctx.cache.store_json(key, document)
    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-ingest-media",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(ctx.jobs_dir, ctx.job_id, media_path),
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
        )
    if initial is JobStatus.INGESTING:
        ctx.manager.transition(ctx.job_id, JobStatus.MEDIA_READY)
    return IngestResult(
        movie=movie, media_path=media_path, cache_hit=cache_hit, duration_ms=duration_ms
    )
