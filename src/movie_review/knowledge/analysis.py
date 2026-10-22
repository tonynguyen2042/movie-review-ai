"""Canonical movie-analysis.json assembly (T039, FR-011).

Merges relational rows (scenes, transcript, characters, locations, events,
relationships, evidence, claims, speaker links) with documentary JSON
artifacts (vision, arcs, themes, twists) into the validated knowledge base.
Owns the ``EVENTS_READY`` → ``STORY_READY`` lifecycle transition.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.domain import Artifact, JobStatus
from movie_review.jobs.failure import job_failure_message
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "story"
STAGE_VERSION = "v1"
ANALYSIS_FILENAME = "movie-analysis.json"

REQUIRED_KEYS = frozenset(
    {
        "movie",
        "scenes",
        "transcript",
        "speakers",
        "characters",
        "locations",
        "events",
        "relationships",
        "evidence",
        "story_arcs",
        "themes",
        "twists",
        "timeline",
    }
)


class AnalysisError(Exception):
    """Analysis assembly failed in a classified way."""


@dataclass
class AnalysisResult:
    """Outcome of one knowledge base assembly."""

    document: dict[str, Any]
    analysis_path: Path
    cache_hit: bool
    duration_ms: int


def _read_artifact_list(jobs_dir: Path, job_id: str, filename: str, key: str) -> list[Any]:
    path = jobs_dir / job_id / STAGE_NAME / filename
    vision_path = jobs_dir / job_id / "vision" / filename
    for candidate in (path, vision_path):
        if candidate.is_file():
            try:
                document = artifacts.read_json(candidate)
            except (OSError, ValueError) as exc:
                raise AnalysisError(f"Cannot read {candidate}: {exc}") from exc
            if not isinstance(document, dict):
                raise AnalysisError(f"Corrupt artifact {candidate}")
            entries = document.get(key, [])
            if not isinstance(entries, list):
                raise AnalysisError(f"Corrupt artifact {candidate}")
            return entries
    return []


def build_movie_analysis(ctx: StageContext) -> AnalysisResult:
    """Assemble ``movie-analysis.json`` for ``ctx.job_id`` to ``STORY_READY``."""
    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise AnalysisError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise AnalysisError(job_failure_message(job))
    owns_completion = job.status is JobStatus.EVENTS_READY

    movie = repo.get_movie(ctx.conn, ctx.job_id)
    if movie is None:
        raise AnalysisError(f"No ingested movie for job {ctx.job_id}")

    jobs_dir = Path(ctx.jobs_dir)
    scenes = repo.list_scenes(ctx.conn, ctx.job_id)
    transcript = repo.list_transcript_segments(ctx.conn, ctx.job_id)
    characters = repo.list_characters(ctx.conn, ctx.job_id)
    locations = repo.list_locations(ctx.conn, ctx.job_id)
    events = repo.list_events(ctx.conn, ctx.job_id)
    relationships = repo.list_relationships(ctx.conn, ctx.job_id)
    evidence = repo.list_evidence(ctx.conn, ctx.job_id)
    claims = repo.list_claims(ctx.conn, ctx.job_id)
    speakers = [
        {"speaker": speaker, "character_id": character_id, "confidence": confidence}
        for speaker, character_id, confidence in repo.list_speaker_links(ctx.conn, ctx.job_id)
    ]
    # The arcs, the themes and the twists have tables of their own, so they
    # are read from the database. They used to be read back out of the JSON
    # artifacts because they had nowhere else to live, which meant a query
    # could not reach them.
    arcs = [arc.model_dump(mode="json") for arc in repo.list_story_arcs(ctx.conn, ctx.job_id)]
    themes = [theme.model_dump(mode="json") for theme in repo.list_themes(ctx.conn, ctx.job_id)]
    twists = [twist.model_dump(mode="json") for twist in repo.list_twists(ctx.conn, ctx.job_id)]
    # From the database, like every other consumer of the visual analyses. The
    # other three lists here still come from their artifacts because they have no
    # table of their own.
    analyses_by_scene = {
        analysis.scene_id: analysis.model_dump(mode="json")
        for analysis in repo.list_scene_analyses(ctx.conn, ctx.job_id)
    }

    document: dict[str, Any] = {
        "movie": movie.model_dump(mode="json"),
        "scenes": [
            {**scene.model_dump(mode="json"), "analysis": analyses_by_scene.get(scene.scene_id)}
            for scene in scenes
        ],
        "transcript": [segment.model_dump(mode="json") for segment in transcript],
        "speakers": speakers,
        "characters": [character.model_dump(mode="json") for character in characters],
        "locations": [location.model_dump(mode="json") for location in locations],
        "events": [event.model_dump(mode="json") for event in events],
        "relationships": [edge.model_dump(mode="json") for edge in relationships],
        "evidence": [item.model_dump(mode="json") for item in evidence],
        "claims": [claim.model_dump(mode="json") for claim in claims],
        "story_arcs": arcs,
        "themes": themes,
        "twists": twists,
        "timeline": [
            {"event_id": event.id, "timestamp": event.timestamp, "type": event.type.value}
            for event in events
        ],
    }
    missing = REQUIRED_KEYS - document.keys()
    if missing:
        raise AnalysisError(f"Analysis missing keys: {sorted(missing)}")

    key = _assembly_key(document)
    cached = ctx.cache.lookup_json(key)
    analysis_path = jobs_dir / ctx.job_id / ANALYSIS_FILENAME
    if cached is not None:
        try:
            cached_keys = set(cached.keys())
        except AttributeError as exc:
            raise AnalysisError("Cached movie-analysis.json is corrupt") from exc
        if REQUIRED_KEYS - cached_keys:
            raise AnalysisError("Cached movie-analysis.json is corrupt")
        cache_hit = True
        document = cached
    else:
        cache_hit = False
        ctx.cache.store_json(key, document)

    output_hash = artifacts.write_json(analysis_path, document)
    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-movie-analysis",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(ctx.jobs_dir, ctx.job_id, analysis_path),
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
        ctx.manager.transition(ctx.job_id, JobStatus.STORY_READY)
    return AnalysisResult(
        document=document,
        analysis_path=analysis_path,
        cache_hit=cache_hit,
        duration_ms=duration_ms,
    )


def _assembly_key(document: dict[str, Any]) -> str:
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return cache_key(
        CacheSpec(
            stage="movie-analysis",
            stage_version=STAGE_VERSION,
            input_hash=artifacts.sha256_bytes(canonical.encode("utf-8")),
        )
    )
