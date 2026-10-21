"""Event extraction stage: analyses + dialogue → LLM → ``events.json`` (T033).

Follows the pipeline stage contract with the T011 lifecycle pattern, moving
``CHARACTERS_READY`` → ``EVENTS_READY``. Scenes are processed in order
with prior events as continuity context (P3 small windows); IDs are assigned
after a global timestamp sort. Uses the shared reasoning port (T033
prerequisite) and the T032 prompt.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.config.prompts import Prompt, load_prompt, render
from movie_review.config.settings import generation_config
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
from movie_review.reasoning.factory import build_reasoning_adapter
from movie_review.reasoning.port import ReasoningPort
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog
from movie_review.vision.analysis import DialogueIndex, _join_dialogue

_logger = logging.getLogger(__name__)

STAGE_NAME = "events"
STAGE_VERSION = "v1"
EVENTS_FILENAME = "events.json"
MAX_PRIOR_EVENTS = 20

#: How many scenes are extracted at once. The scenes in a batch run
#: concurrently; the batch before it supplies the continuity context.
DEFAULT_BATCH_SIZE = 8

#: How many scenes are extracted at the same time.
DEFAULT_CONCURRENCY = 4


#: How many characters are named in a per-scene prompt. The whole roster
#: used to be sent to every scene: 532 discovered candidates made an 11.9
#: KB block, and a thousand scene prompts carried about three million tokens
#: of the same names.
MAX_SCENE_CHARACTERS = 12


def _scene_character_lines(
    characters: list[Character],
    analysis: SceneAnalysis,
    limit: int = MAX_SCENE_CHARACTERS,
) -> str:
    """The characters worth naming for one scene.

    The characters the scene's own analysis mentions come first, then the
    most important of the rest, and the list is capped. The whole roster
    was sent to every scene before, which for a feature film was three
    million tokens of the same names.
    """
    if not characters:
        return "none yet"

    mentioned = {name.strip().lower() for name in analysis.characters if name.strip()}
    named = [c for c in characters if c.name.strip().lower() in mentioned]
    others = [c for c in characters if c.name.strip().lower() not in mentioned]

    chosen = named[:limit]
    if len(chosen) < limit:
        chosen = chosen + others[: limit - len(chosen)]
    if not chosen:
        return "none yet"

    lines = [f"{c.id}: {c.name}" for c in chosen]
    if len(named) > limit:
        lines.append(f"... and {len(named) - limit} more named in this scene")
    return "\n".join(lines)


def _batches(scenes: list[Scene], size: int) -> list[list[Scene]]:
    """Split the scenes into batches of at most ``size``."""
    if size <= 1:
        return [[scene] for scene in scenes]
    return [scenes[index : index + size] for index in range(0, len(scenes), size)]


def _extract_one(
    scene: Scene,
    analysis: SceneAnalysis,
    dialogue: str,
    prior: list[dict[str, object]],
    prompt: Prompt,
    model: str,
    character_lines: str,
    active: ReasoningPort,
    ctx: StageContext,
) -> tuple[list[dict[str, object]], bool]:
    """Extract one scene's events: cache lookup, then the model."""
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
        prompt_version=prompt.cache_version,
        generation_config=generation_config(ctx.settings.models.reasoning),
    )
    key = cache_key(spec)
    cached = ctx.cache.lookup_json(key)
    if cached is not None:
        if not isinstance(cached, list):
            raise EventExtractionError(f"Cached events corrupt for {scene.scene_id}")
        return cached, True

    try:
        entries = active.complete_json(text)
    except Exception as exc:
        raise EventExtractionError(f"Cannot extract events for {scene.scene_id}: {exc}") from exc
    if not isinstance(entries, list):
        raise EventExtractionError(f"Expected event array for {scene.scene_id}")
    ctx.cache.store_json(key, entries)
    return entries, False


def _extract_batch(
    batch: list[Scene],
    analyses: dict[str, SceneAnalysis],
    dialogue_index: DialogueIndex,
    prompt: Prompt,
    model: str,
    character_lines: str,
    prior: list[dict[str, object]],
    characters: list[Character],
    active: ReasoningPort,
    ctx: StageContext,
) -> list[tuple[list[dict[str, object]], bool]]:
    """Extract a batch of scenes concurrently, preserving their order."""
    if not batch:
        return []

    def work(scene: Scene) -> tuple[list[dict[str, object]], bool]:
        analysis = analyses.get(scene.scene_id)
        if analysis is None:
            raise EventExtractionError(f"No analysis for {scene.scene_id}")
        dialogue = _join_dialogue(dialogue_index.window(scene.start, scene.end))
        return _extract_one(
            scene,
            analysis,
            dialogue,
            prior,
            prompt,
            model,
            _scene_character_lines(characters, analysis),
            active,
            ctx,
        )

    if len(batch) == 1 or DEFAULT_CONCURRENCY <= 1:
        return [work(scene) for scene in batch]

    with ThreadPoolExecutor(max_workers=min(DEFAULT_CONCURRENCY, len(batch))) as pool:
        # `map` keeps the order of the input, so the results line up with the
        # scenes no matter which finished first.
        return list(pool.map(work, batch))


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
    batch_size: int = DEFAULT_BATCH_SIZE,
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
    active = reasoner or build_reasoning_adapter(ctx.settings.models.reasoning)
    # The adapter's own model, not its class name: a class-name key gives every
    # remote model the same cache entry, so switching models silently reuses the
    # previous model's output.
    model = active.model
    character_lines = "\n".join(f"{c.id}: {c.name}" for c in characters) or "none yet"

    raw_entries: list[dict[str, object]] = []
    cache_hits = 0
    # The continuity context: each scene is told which events came before it.
    # Extracting one scene per round trip, strictly in order, made the stage
    # as slow as the number of scenes -- hundreds of sequential calls for a
    # feature film.
    #
    # The scenes are extracted in batches instead. Within a batch they run
    # concurrently and each one is told about the batch before it, so the
    # continuity still crosses the scenes; the scene immediately before it
    # inside the same batch is not in the context, which is the trade.
    prior: list[dict[str, object]] = []
    # The transcript is indexed once: the dialogue of every scene is found
    # with two bisects instead of a scan of the whole transcript.
    dialogue_index = DialogueIndex(segments)
    try:
        for batch in _batches(scenes, batch_size):
            results = _extract_batch(
                batch,
                analyses,
                dialogue_index,
                prompt,
                model,
                character_lines,
                prior,
                characters,
                active,
                ctx,
            )
            for entries, hit in results:
                if hit:
                    cache_hits += 1
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise EventExtractionError("Malformed event entry")
                    prior.append(entry)
                raw_entries.extend(entries)
    except Exception as exc:
        if owns_completion:
            # The workers raise; the failure is recorded here, from the
            # thread that owns the connection.
            ctx.manager.fail(ctx.job_id, STAGE_NAME, str(exc))
        raise
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

    # One transaction for the whole stage: the events stage writes one row
    # per event, and each write was its own commit.
    # Every AI output passes schema validation before it enters the next
    # stage (README section 6.6).
    from movie_review.schemas import SchemaError, validate_artifact

    for event in events:
        try:
            validate_artifact("event", event.model_dump(mode="json"))
        except SchemaError as exc:
            if owns_completion:
                ctx.manager.fail(ctx.job_id, STAGE_NAME, str(exc))
            raise EventExtractionError(str(exc)) from exc

    repo.save_events(ctx.conn, ctx.job_id, events)
    document = {
        "job_id": ctx.job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "prompt": prompt.cache_version,
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
            relative_path=artifacts.relative_artifact_path(ctx.jobs_dir, ctx.job_id, events_path),
            input_hash=_run_input_hash(scenes),
            output_hash=output_hash,
            model=model,
            prompt_version=prompt.cache_version,
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
    """The identity of one scene's extraction.

    Only the events the prompt carries are hashed. The whole prior list
    used to be hashed, although the prompt shows the last twenty of them,
    so the key grew with the length of the film and a change to an early
    event invalidated every later scene's entry.
    """
    material = "|".join(
        [
            scene.scene_id,
            f"{scene.start:.3f}",
            f"{scene.end:.3f}",
            dialogue,
            json.dumps(prior[-MAX_PRIOR_EVENTS:], sort_keys=True),
        ]
    )
    return artifacts.sha256_bytes(material.encode("utf-8"))


def _run_input_hash(scenes: list[Scene]) -> str:
    return artifacts.sha256_bytes(
        "|".join(f"{scene.scene_id}:{scene.start:.3f}:{scene.end:.3f}" for scene in scenes).encode(
            "utf-8"
        )
    )
