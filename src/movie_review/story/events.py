"""Event extraction stage: analyses + dialogue → LLM → ``events.json`` (T033).

Follows the pipeline stage contract with the T011 lifecycle pattern, moving
``VISUAL_ANALYSIS_READY`` → ``EVENTS_READY``. Scenes are processed in order
with prior events as continuity context (P3 small windows); IDs are assigned
after a global timestamp sort. Uses the shared reasoning port (T033
prerequisite) and the T032 prompt.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.config.prompts import load_prompt, render
from movie_review.domain import (
    Artifact,
    Character,
    Event,
    JobStatus,
    Scene,
    SceneAnalysis,
    TranscriptSegment,
)
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.context import StageContext
from movie_review.reasoning.port import ReasoningPort
from movie_review.reasoning.qwen import QwenReasoningAdapter
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog
from movie_review.vision.analysis import scene_dialogue

_logger = logging.getLogger(__name__)

STAGE_NAME = "events"
STAGE_VERSION = "v1"
EVENTS_FILENAME = "events.json"
MAX_PRIOR_EVENTS = 20


class EventExtractionError(Exception):
    """Event extraction stage failed in a classified way."""


@dataclass
class EventsResult:
    """Outcome of one event extraction run."""

    events: list[Event]
    events_path: Path
    cache_hits: int
    duration_ms: int


def _prior_lines(prior: list[dict[str, object]]) -> str:
    if not prior:
        return "none"
    return "\n".join(
        f"{entry['type']} @ {entry['timestamp']}: {entry['description']}"
        for entry in prior[-MAX_PRIOR_EVENTS:]
    )


def run_event_extraction(
    scenes: list[Scene],
    analyses: dict[str, SceneAnalysis],
    segments: list[TranscriptSegment],
    characters: list[Character],
    ctx: StageContext,
    reasoner: ReasoningPort | None = None,
    prompt_version: str | None = None,
) -> EventsResult:
    """Extract story events for ``ctx.job_id`` through to ``EVENTS_READY``."""
    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise EventExtractionError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise EventExtractionError(f"Job {ctx.job_id} failed; resume arrives in T085")
    # Entry is CHARACTERS_READY per the T006 chain; the driver that sequences
    # discovery/linking into that state arrives with orchestration (T084+).
    owns_completion = job.status is JobStatus.CHARACTERS_READY

    prompt = load_prompt("event_extraction", prompt_version)
    active = reasoner or QwenReasoningAdapter(ctx.settings.models.reasoning.model)
    model = active.model if isinstance(active, QwenReasoningAdapter) else type(active).__name__
    character_lines = "\n".join(f"{c.id}: {c.name}" for c in characters) or "none yet"

    raw_entries: list[dict[str, object]] = []
    cache_hits = 0
    prior: list[dict[str, object]] = []
    try:
        for scene in scenes:
            analysis = analyses.get(scene.scene_id)
            if analysis is None:
                raise EventExtractionError(f"No analysis for {scene.scene_id}")
            dialogue = scene_dialogue(segments, scene.start, scene.end)
            text = render(
                prompt,
                scenes=f"{scene.scene_id} ({scene.start:.1f}-{scene.end:.1f}s): "
                f"{analysis.location}; {'; '.join(analysis.actions)}",
                dialogue=dialogue or "(no dialogue)",
                characters=character_lines,
                prior_events=_prior_lines(prior),
            )
            spec = CacheSpec(
                stage=STAGE_NAME,
                stage_version=STAGE_VERSION,
                input_hash=_scene_input_hash(scene, dialogue, prior),
                model_id=model,
                prompt_version=f"{prompt.name}:{prompt.version}",
            )
            key = cache_key(spec)
            cached = ctx.cache.lookup_json(key)
            if cached is not None:
                if not isinstance(cached, list):
                    if owns_completion:
                        ctx.manager.fail(ctx.job_id, STAGE_NAME, "cached events corrupt")
                    raise EventExtractionError(f"Cached events corrupt for {scene.scene_id}")
                entries = cached
                cache_hits += 1
            else:
                try:
                    entries = active.complete_json(text)
                except Exception as exc:
                    if owns_completion:
                        ctx.manager.fail(ctx.job_id, STAGE_NAME, f"{scene.scene_id}: {exc}")
                    raise EventExtractionError(
                        f"Cannot extract events for {scene.scene_id}: {exc}"
                    ) from exc
                if not isinstance(entries, list):
                    raise EventExtractionError(f"Expected event array for {scene.scene_id}")
                ctx.cache.store_json(key, entries)
            for entry in entries:
                if not isinstance(entry, dict):
                    if owns_completion:
                        ctx.manager.fail(ctx.job_id, STAGE_NAME, "malformed event entry")
                    raise EventExtractionError(f"Malformed event entry for {scene.scene_id}")
                prior.append(entry)
            raw_entries.extend(entries)
    finally:
        active.unload()

    ordered = sorted(raw_entries, key=lambda e: float(cast("float", e.get("timestamp", 0.0))))
    events = []
    for index, entry in enumerate(ordered, start=1):
        try:
            events.append(Event(id=f"event_{index:05d}", **entry))  # type: ignore[arg-type]
        except ValueError as exc:
            if owns_completion:
                ctx.manager.fail(ctx.job_id, STAGE_NAME, f"invalid event: {exc}")
            raise EventExtractionError(f"Invalid extracted event: {exc}") from exc

    for event in events:
        repo.save_event(ctx.conn, ctx.job_id, event)
    document = {
        "job_id": ctx.job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "prompt": f"{prompt.name}:{prompt.version}",
        "model": model,
        "events": [event.model_dump(mode="json") for event in events],
    }
    events_path = artifacts.artifact_path(ctx.jobs_dir, ctx.job_id, STAGE_NAME, EVENTS_FILENAME)
    output_hash = artifacts.write_json(events_path, document)
    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-events",
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
            events=len(events),
        )
    if owns_completion:
        ctx.manager.transition(ctx.job_id, JobStatus.EVENTS_READY)
    return EventsResult(
        events=events,
        events_path=events_path,
        cache_hits=cache_hits,
        duration_ms=duration_ms,
    )


def _scene_input_hash(scene: Scene, dialogue: str, prior: list[dict[str, object]]) -> str:
    material = "|".join(
        [
            scene.scene_id,
            f"{scene.start:.3f}",
            f"{scene.end:.3f}",
            dialogue,
            json.dumps(prior, sort_keys=True),
        ]
    )
    return artifacts.sha256_bytes(material.encode("utf-8"))


def _run_input_hash(scenes: list[Scene]) -> str:
    return artifacts.sha256_bytes(
        "|".join(f"{scene.scene_id}:{scene.start:.3f}:{scene.end:.3f}" for scene in scenes).encode(
            "utf-8"
        )
    )
