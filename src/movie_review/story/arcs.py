"""Story arc extraction from ordered events (T036, README section 23).

Artifact-only extraction: no job-lifecycle transition (no per-extraction
state exists); the STORY_READY milestone belongs to the T039 assembly.
Uses the shared reasoning port and the T036 prompt.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.cache.manager import CacheManager
from movie_review.config.prompts import load_prompt, render
from movie_review.config.settings import ModelSpec, generation_config
from movie_review.domain import Artifact, Event, StoryArc
from movie_review.pipeline.model_runs import record_model_run
from movie_review.reasoning.factory import build_reasoning_adapter
from movie_review.reasoning.port import ReasoningPort
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "story"
STAGE_VERSION = "v1"
ARCS_FILENAME = "story-arcs.json"
MAX_EVENTS = 100


class StoryArcError(Exception):
    """Story arc extraction failed in a classified way."""


@dataclass
class ArcsResult:
    """Outcome of one arc extraction run."""

    arcs: list[StoryArc]
    arcs_path: Path
    cache_hit: bool


def extract_story_arcs(
    events: list[Event],
    characters: str,
    *,
    job_id: str,
    jobs_dir: str | Path,
    conn: sqlite3.Connection,
    cache: CacheManager,
    spec: ModelSpec,
    reasoner: ReasoningPort | None = None,
    prompt_version: str | None = None,
) -> ArcsResult:
    """Map ordered events to story arcs; persists ``story-arcs.json``.

    ``spec`` is the configured reasoning model. The adapter is built from it, so
    ``backend: openai_compatible`` routes to a remote endpoint. Constructing
    QwenReasoningAdapter directly ignored the configured backend and demanded MLX
    on every host.
    """
    if not events:
        raise StoryArcError("Event extraction must run before story arcs")
    prompt = load_prompt("story_arc", prompt_version)
    active = reasoner or build_reasoning_adapter(spec)
    # The adapter's own model, not its class name: a class-name key gives every
    # remote model the same cache entry, so switching models silently reuses the
    # previous model's output.
    model_id = active.model

    selected = sorted(events, key=lambda e: (-e.importance, e.timestamp))[:MAX_EVENTS]
    selected = sorted(selected, key=lambda e: e.timestamp)
    event_lines = "\n".join(
        f"{event.id} [{event.type.value} @ {event.timestamp:.1f}]: {event.description}"
        for event in selected
    )
    text = render(prompt, events=event_lines, characters=characters or "none yet")
    cache_spec = CacheSpec(
        stage=STAGE_NAME,
        stage_version=STAGE_VERSION,
        # The whole rendered prompt is the input, not a fragment of it.
        # The prompt carries the character roster as well as the events, so
        # hashing only the events left a re-run with a different roster
        # serving the previous model's answer -- one generated against the
        # old roster.
        input_hash=artifacts.sha256_bytes(text.encode("utf-8")),
        model_id=model_id,
        prompt_version=prompt.cache_version,
        generation_config=generation_config(spec),
    )
    key = cache_key(cache_spec)
    try:
        cached = cache.lookup_json(key)
        if cached is not None:
            if not isinstance(cached, list):
                raise StoryArcError("Cached story arcs are corrupt")
            raw = cached
            cache_hit = True
        else:
            try:
                with record_model_run(
                    conn,
                    job_id,
                    STAGE_NAME,
                    active,
                    model_id,
                    prompt_hash=key,
                    prompt_version=prompt.cache_version,
                    temperature=spec.generation.temperature,
                ):
                    raw = active.complete_json(text)
            except Exception as exc:
                raise StoryArcError(f"Cannot extract story arcs: {exc}") from exc
            if not isinstance(raw, list):
                raise StoryArcError("Expected story arc array")
            cache.store_json(key, raw)
            cache_hit = False
    finally:
        # The adapter owns the weights, so it is released whether the work
        # came from the cache or from the model. The unload used to sit in
        # the cache-miss branch: a cache hit skipped the model call and also
        # skipped the release, so the weights stayed resident for the rest of
        # the process -- and for the MLX backends, `unload` is what clears
        # the cache.
        active.unload()

    arcs = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise StoryArcError("Malformed story arc entry")
        try:
            arcs.append(StoryArc.model_validate(entry))
        except ValueError as exc:
            raise StoryArcError(f"Invalid story arc: {exc}") from exc
    for arc in arcs:
        if arc.applicable and not arc.event_ids:
            raise StoryArcError(f"Applicable arc {arc.element} cites no events")

    # The arcs have a table of their own, so a query can reach them.
    repo.save_story_arcs(conn, job_id, arcs)

    document = {
        "job_id": job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "prompt": prompt.cache_version,
        "model": model_id,
        "arcs": [arc.model_dump(mode="json") for arc in arcs],
    }
    arcs_path = artifacts.artifact_path(jobs_dir, job_id, STAGE_NAME, ARCS_FILENAME)
    output_hash = artifacts.write_json(arcs_path, document)
    repo.save_artifact(
        conn,
        Artifact(
            artifact_id=f"{job_id}-story-arcs",
            job_id=job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(jobs_dir, job_id, arcs_path),
            input_hash=key,
            output_hash=output_hash,
            model=model_id,
            prompt_version=prompt.cache_version,
        ),
    )
    with ulog.logging_context(job_id=job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="story.completed",
            status="ok",
            cache_hit=cache_hit,
            arcs=len(arcs),
        )
    return ArcsResult(arcs=arcs, arcs_path=arcs_path, cache_hit=cache_hit)
