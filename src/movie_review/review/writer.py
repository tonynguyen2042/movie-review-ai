"""Review script writer: outline + evidence → LLM → ``review-script.json`` (T044).

Writes one section per outline entry with small, retryable model calls (P3).
Consumes the T041 outline and the T043 prompt; validates section order and
claim shapes. Advances ``STORY_READY`` → ``REVIEW_PLAN_READY`` (plan
adoption) → ``SCRIPT_READY`` since no other task owns those milestones.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.config.prompts import load_prompt, render
from movie_review.config.settings import ModelSpec
from movie_review.domain import Artifact, JobStatus, ReviewPlan, ReviewScript, ReviewSection
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.context import StageContext
from movie_review.reasoning.factory import build_reasoning_adapter
from movie_review.reasoning.port import ReasoningPort
from movie_review.review.styles import StyleProfile
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "review"
STAGE_VERSION = "v1"
SCRIPT_FILENAME = "review-script.json"
MAX_EVENTS = 60


class ScriptWriterError(Exception):
    """Script writing failed in a classified way."""


@dataclass
class ScriptResult:
    """Outcome of one script writing run."""

    script: ReviewScript
    script_path: Path
    cache_hits: int
    word_count: int


def _story_brief(analysis: dict[str, Any]) -> str:
    events = analysis.get("events", [])
    if not isinstance(events, list):
        events = []
    lines = []
    for event in sorted(events, key=lambda e: float(e.get("timestamp", 0.0)))[:MAX_EVENTS]:
        if not isinstance(event, dict):
            continue
        lines.append(f"{event.get('id')}: {event.get('description', '')}")
    characters = analysis.get("characters", [])
    themes = [t["theme"] if isinstance(t, dict) else t for t in analysis.get("themes", [])]
    twists = [t["description"] if isinstance(t, dict) else t for t in analysis.get("twists", [])]
    return (
        "events:\n" + "\n".join(lines) + f"\ncharacters: {characters}\nthemes: {themes}\n"
        f"twists: {twists}"
    )


def write_script(
    outline: ReviewPlan,
    analysis: dict[str, Any],
    style: StyleProfile,
    target_words: int,
    ctx: StageContext,
    spec: ModelSpec,
    reasoner: ReasoningPort | None = None,
    prompt_version: str | None = None,
    spoilers: str | None = None,
) -> ScriptResult:
    """Write narration for ``ctx.job_id`` through to ``SCRIPT_READY``.

    ``spec`` is the configured reasoning model. The adapter is built from it, so
    ``backend: openai_compatible`` routes to a remote endpoint. Constructing
    QwenReasoningAdapter directly ignored the configured backend and demanded MLX
    on every host.
    """
    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise ScriptWriterError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise ScriptWriterError(f"Job {ctx.job_id} failed; resume arrives in T085")
    owns_completion = job.status is JobStatus.STORY_READY
    if target_words <= 0:
        raise ScriptWriterError(f"Target words must be positive: {target_words}")

    prompt = load_prompt("script_writer", prompt_version)
    active = reasoner or build_reasoning_adapter(spec)
    # The adapter's own model, not its class name: a class-name key gives every
    # remote model the same cache entry, so switching models silently reuses the
    # previous model's output.
    model_id = active.model
    story = _story_brief(analysis)
    total_seconds = sum(section.target_seconds for section in outline.sections)
    run_hash = artifacts.sha256_bytes(
        f"{outline.model_dump_json()}|{story}|{target_words}".encode()
    )

    if owns_completion:
        ctx.manager.transition(ctx.job_id, JobStatus.REVIEW_PLAN_READY)

    sections: list[ReviewSection] = []
    cache_hits = 0
    try:
        for section in outline.sections:
            share = max(1, round(target_words * section.target_seconds / total_seconds))
            text = render(
                prompt,
                outline=(
                    f"{section.id} ({section.type}): {section.purpose}; events {section.event_ids}"
                ),
                story=story,
                style=f"{style.name} ({style.tone})",
                target_words=str(share),
                spoilers=spoilers or style.spoilers,
            )
            cache_spec = CacheSpec(
                stage=STAGE_NAME,
                stage_version=STAGE_VERSION,
                input_hash=artifacts.sha256_bytes(
                    "|".join(
                        [section.id, story, str(share), style.name, spoilers or style.spoilers]
                    ).encode()
                ),
                model_id=model_id,
                prompt_version=prompt.cache_version,
            )
            key = cache_key(cache_spec)
            cached = ctx.cache.lookup_json(key)
            if cached is not None:
                try:
                    parsed = ReviewSection.model_validate(cached["section"])
                except (KeyError, TypeError, ValueError) as exc:
                    if owns_completion:
                        ctx.manager.fail(ctx.job_id, STAGE_NAME, "cached script corrupt")
                    raise ScriptWriterError(f"Cached script corrupt for {section.id}") from exc
                cache_hits += 1
            else:
                try:
                    raw = active.complete_json(text)
                except Exception as exc:
                    if owns_completion:
                        ctx.manager.fail(ctx.job_id, STAGE_NAME, f"{section.id}: {exc}")
                    raise ScriptWriterError(f"Cannot write {section.id}: {exc}") from exc
                if not isinstance(raw, dict) or "sections" not in raw:
                    if owns_completion:
                        ctx.manager.fail(ctx.job_id, STAGE_NAME, "malformed script output")
                    raise ScriptWriterError(f"Malformed script output for {section.id}")
                found = [s for s in raw["sections"] if isinstance(s, dict)]
                if len(found) != 1:
                    if owns_completion:
                        ctx.manager.fail(ctx.job_id, STAGE_NAME, "section count mismatch")
                    raise ScriptWriterError(
                        f"Expected one section for {section.id}, got {len(found)}"
                    )
                try:
                    parsed = ReviewSection.model_validate(found[0])
                except ValueError as exc:
                    if owns_completion:
                        ctx.manager.fail(ctx.job_id, STAGE_NAME, f"invalid {section.id}")
                    raise ScriptWriterError(f"Invalid section {section.id}: {exc}") from exc
                ctx.cache.store_json(key, {"section": parsed.model_dump(mode="json")})
            if parsed.type != section.type:
                if owns_completion:
                    ctx.manager.fail(ctx.job_id, STAGE_NAME, "section order violated")
                raise ScriptWriterError(
                    f"Section order violated: expected {section.type}, got {parsed.type}"
                )
            sections.append(parsed)
    finally:
        active.unload()

    script = ReviewScript(sections=sections)
    word_count = sum(len(p.text.split()) for s in sections for p in s.paragraphs)
    document = {
        "job_id": ctx.job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "prompt": prompt.cache_version,
        "model": model_id,
        "word_count": word_count,
        "script": script.model_dump(mode="json"),
    }
    script_path = artifacts.artifact_path(ctx.jobs_dir, ctx.job_id, STAGE_NAME, SCRIPT_FILENAME)
    output_hash = artifacts.write_json(script_path, document)
    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-review-script",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(ctx.jobs_dir, ctx.job_id, script_path),
            input_hash=run_hash,
            output_hash=output_hash,
            model=model_id,
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
            word_count=word_count,
        )
    if owns_completion:
        ctx.manager.transition(ctx.job_id, JobStatus.SCRIPT_READY)
    return ScriptResult(
        script=script,
        script_path=script_path,
        cache_hits=cache_hits,
        word_count=word_count,
    )
