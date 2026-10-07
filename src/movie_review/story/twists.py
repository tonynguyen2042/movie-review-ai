"""Twist detection from ordered events (T038, README section 24).

Artifact-only extraction like arcs/themes: no job-lifecycle transition (the
STORY_READY milestone belongs to the T039 assembly). Every twist must cite
at least two foreshadowing events that resolve to known event IDs — a twist
inferred from a single response alone is rejected, never stored.
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
from movie_review.domain import Artifact, Event, Twist
from movie_review.reasoning.port import ReasoningPort
from movie_review.reasoning.qwen import QwenReasoningAdapter
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "story"
STAGE_VERSION = "v1"
TWISTS_FILENAME = "twists.json"
MAX_EVENTS = 100
MIN_FORESHADOWING = 2


class TwistExtractionError(Exception):
    """Twist detection failed in a classified way."""


@dataclass
class TwistsResult:
    """Outcome of one twist detection run."""

    twists: list[Twist]
    twists_path: Path
    cache_hit: bool


def extract_twists(
    events: list[Event],
    characters: str,
    *,
    job_id: str,
    jobs_dir: str | Path,
    conn: sqlite3.Connection,
    cache: CacheManager,
    model: str,
    reasoner: ReasoningPort | None = None,
    prompt_version: str | None = None,
) -> TwistsResult:
    """Detect evidenced twists; persists ``twists.json``."""
    if not events:
        raise TwistExtractionError("Event extraction must run before twists")
    prompt = load_prompt("twist", prompt_version)
    active = reasoner or QwenReasoningAdapter(model)
    model_id = active.model if isinstance(active, QwenReasoningAdapter) else type(active).__name__

    selected = sorted(events, key=lambda e: (-e.importance, e.timestamp))[:MAX_EVENTS]
    selected = sorted(selected, key=lambda e: e.timestamp)
    known_ids = {event.id for event in selected}
    event_lines = "\n".join(
        f"{event.id} [{event.type.value} @ {event.timestamp:.1f}]: {event.description}"
        for event in selected
    )
    text = render(prompt, events=event_lines, characters=characters or "none yet")
    spec = CacheSpec(
        stage="twists",
        stage_version=STAGE_VERSION,
        input_hash=artifacts.sha256_bytes(event_lines.encode("utf-8")),
        model_id=model_id,
        prompt_version=f"{prompt.name}:{prompt.version}",
    )
    key = cache_key(spec)
    cached = cache.lookup_json(key)
    if cached is not None:
        if not isinstance(cached, list):
            raise TwistExtractionError("Cached twists are corrupt")
        raw = cached
        cache_hit = True
    else:
        try:
            raw = active.complete_json(text)
        except Exception as exc:
            raise TwistExtractionError(f"Cannot detect twists: {exc}") from exc
        finally:
            active.unload()
        if not isinstance(raw, list):
            raise TwistExtractionError("Expected twist array")
        cache.store_json(key, raw)
        cache_hit = False

    twists = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise TwistExtractionError("Malformed twist entry")
        try:
            twist = Twist(id=f"twist_{index:03d}", **entry)
        except ValueError as exc:
            raise TwistExtractionError(f"Invalid twist: {exc}") from exc
        unknown = [ref for ref in twist.foreshadowed_by if ref not in known_ids]
        if unknown:
            raise TwistExtractionError(f"Twist cites unknown events: {unknown}")
        if len(twist.foreshadowed_by) < MIN_FORESHADOWING:
            raise TwistExtractionError(
                f"Twist {twist.id} needs at least {MIN_FORESHADOWING} foreshadowing events"
            )
        twists.append(twist)

    document = {
        "job_id": job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "prompt": f"{prompt.name}:{prompt.version}",
        "model": model_id,
        "twists": [twist.model_dump(mode="json") for twist in twists],
    }
    twists_path = artifacts.artifact_path(jobs_dir, job_id, STAGE_NAME, TWISTS_FILENAME)
    output_hash = artifacts.write_json(twists_path, document)
    repo.save_artifact(
        conn,
        Artifact(
            artifact_id=f"{job_id}-twists",
            job_id=job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(jobs_dir, job_id, twists_path),
            input_hash=key,
            output_hash=output_hash,
            model=model_id,
            prompt_version=f"{prompt.name}:{prompt.version}",
        ),
    )
    with ulog.logging_context(job_id=job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="twists.completed",
            status="ok",
            cache_hit=cache_hit,
            twists=len(twists),
        )
    return TwistsResult(twists=twists, twists_path=twists_path, cache_hit=cache_hit)
