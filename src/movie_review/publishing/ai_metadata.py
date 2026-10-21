"""Model-driven publishing metadata (T110).

:mod:`movie_review.publishing.metadata` builds a title from a template and the
script's first sentence. That is descriptive but not attention-grabbing, which is
what the packaging on a social platform has to do. This module asks the reasoning
model for a title, description and tags, constrained by the narration.

The constraint is the point. AGENTS.md forbids inventing dialogue, scenes,
relationships, deaths or plot facts, and the same applies here with more force:
a clickbait title is a factual claim made to an audience that cannot check it.
So the model may write about the review and offer opinion, but may not assert
anything about the film that the narration does not state.

The model's output is normalized against each platform's field limits and the
result is persisted and recorded as an artifact, so a run can be reproduced and
the packaging can be regenerated after an edit without touching the video.
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
from movie_review.config.prompts import load_prompt, render
from movie_review.config.settings import ModelSpec
from movie_review.domain import Artifact, ReviewScript
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.context import StageContext
from movie_review.publishing.metadata import (
    DESCRIPTION_MAX_CHARS,
    TITLE_MAX_CHARS,
    Chapter,
    VideoMetadata,
)
from movie_review.reasoning.factory import build_reasoning_adapter
from movie_review.reasoning.port import ReasoningPort
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

STAGE_NAME = "publishing"
STAGE_VERSION = "v1"
METADATA_FILENAME = "publishing-metadata.json"

#: Cap on how much narration is sent. The prompt asks for packaging for the
#: video as a whole; the opening is what carries the hook and the argument, and
#: sending a whole 20-minute transcript would blow the context for no gain.
NARRATION_EXCERPT_CHARS = 6000

#: Status marker for a claim the narration does not support. The prompt forbids it
#: as a hook, and it is stripped from output rather than published.
EVIDENCE_MARKER = "INSUFFICIENT_EVIDENCE"

_logger = logging.getLogger(__name__)


class PublishingMetadataError(Exception):
    """Metadata generation failed in a classified way."""


class UnsupportedClaimError(PublishingMetadataError):
    """The model's output asserted something the narration does not support."""


@dataclass(frozen=True)
class MetadataResult:
    """Outcome of one metadata generation run."""

    metadata: VideoMetadata
    metadata_path: Path
    cache_hit: bool
    model: str
    prompt_version: str


def narration_excerpt(script: ReviewScript, limit: int = NARRATION_EXCERPT_CHARS) -> str:
    """Narration text to send to the model, truncated on a paragraph boundary."""
    parts = [paragraph.text for section in script.sections for paragraph in section.paragraphs]
    text = "\n".join(parts)
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    boundary = clipped.rfind("\n")
    if boundary > 0:
        clipped = clipped[:boundary]
    return clipped


def _clean(value: object, field: str) -> str:
    """One string field from the model's output, or a classified failure."""
    if not isinstance(value, str):
        raise PublishingMetadataError(f"Model returned a non-string {field}")
    text = " ".join(value.split())
    if not text:
        raise PublishingMetadataError(f"Model returned an empty {field}")
    if EVIDENCE_MARKER in text:
        # The marker is a status code for a claim nobody could support. It must
        # never reach a viewer, and a title that needs it is not publishable.
        raise UnsupportedClaimError(
            f"Model put {EVIDENCE_MARKER} in the {field}; the narration does not "
            f"support the claim it is marking"
        )
    return text


def _clean_tags(value: object) -> list[str]:
    """Tags from the model's output: strings, de-duplicated, no marker."""
    if not isinstance(value, list):
        raise PublishingMetadataError("Model returned non-list tags")
    tags: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise PublishingMetadataError("Model returned a non-string tag")
        if EVIDENCE_MARKER in item:
            raise UnsupportedClaimError(f"Model put {EVIDENCE_MARKER} in a tag")
        tag = item.strip().lstrip("#").strip()
        if tag and tag.lower() not in {existing.lower() for existing in tags}:
            tags.append(tag)
    if not tags:
        raise PublishingMetadataError("Model returned no usable tags")
    return tags


def _truncate(value: str, limit: int) -> str:
    """Trim to ``limit`` characters on a word boundary."""
    if len(value) <= limit:
        return value
    clipped = value[:limit]
    boundary = clipped.rfind(" ")
    if boundary > 0:
        clipped = clipped[:boundary]
    return clipped.rstrip()


def parse_metadata(raw: object) -> dict[str, Any]:
    """Validate the model's reply into title, description and tags.

    Raises rather than repairing: a title is the one field a viewer reads before
    deciding anything, so a malformed one is a failure to surface, not something
    to paper over with a fallback template.
    """
    if isinstance(raw, str):
        # Some endpoints answer a JSON request with a fenced or prose-wrapped
        # object; extract_json_output handles that shape.
        from movie_review.reasoning.port import extract_json_output

        raw = extract_json_output(raw)
    if not isinstance(raw, dict):
        raise PublishingMetadataError("Expected a JSON object for publishing metadata")

    title = _clean(raw.get("title"), "title")
    description = _clean(raw.get("description"), "description")
    tags = _clean_tags(raw.get("tags"))
    return {
        "title": _truncate(title, TITLE_MAX_CHARS),
        "description": description[:DESCRIPTION_MAX_CHARS],
        "tags": tags,
    }


def generate_publishing_metadata(
    script: ReviewScript,
    ctx: StageContext,
    *,
    movie_title: str,
    platform: str,
    target_language: str,
    spec: ModelSpec,
    chapters: list[Chapter] | None = None,
    reasoner: ReasoningPort | None = None,
    prompt_version: str | None = None,
) -> MetadataResult:
    """Generate, persist and record publishing metadata for a review video.

    ``spec`` is the reasoning model; the adapter is built from it so
    ``backend: openai_compatible`` routes to a remote endpoint.

    Cached on the narration, the platform, the target language, the model and the
    prompt version, so switching model or editing a prompt produces different
    output rather than reusing the previous run's.
    """
    if not script.sections:
        raise PublishingMetadataError("Cannot generate metadata for an empty script")

    started = time.perf_counter()
    try:
        ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise PublishingMetadataError(f"Unknown job: {ctx.job_id}") from exc

    prompt = load_prompt("publishing_metadata", prompt_version)
    version = prompt.cache_version
    excerpt = narration_excerpt(script)
    text = render(
        prompt,
        movie_title=movie_title or "unknown",
        platform=platform,
        target_language=target_language,
        narration=excerpt,
    )
    input_hash = artifacts.sha256_bytes(text.encode("utf-8"))

    active = reasoner or build_reasoning_adapter(spec)
    # The adapter's own model, not its class name: a class-name key gives every
    # remote model the same cache entry, so switching models silently reuses the
    # previous model's output.
    model_id = active.model

    cache_spec = CacheSpec(
        stage=STAGE_NAME,
        stage_version=STAGE_VERSION,
        input_hash=input_hash,
        model_id=model_id,
        prompt_version=version,
    )
    key = cache_key(cache_spec)

    try:
        cached = ctx.cache.lookup_json(key)
        if cached is not None:
            if not isinstance(cached, dict) or "title" not in cached:
                raise PublishingMetadataError("Cached publishing metadata is corrupt")
            fields = cached
            cache_hit = True
        else:
            try:
                raw = active.complete_json(text)
            except Exception as exc:
                raise PublishingMetadataError(
                    f"Cannot generate publishing metadata: {exc}"
                ) from exc
            fields = parse_metadata(raw)
            ctx.cache.store_json(key, fields)
            cache_hit = False
    finally:
        # The adapter owns the weights, so it is released whether the work
        # came from the cache or from the model. The unload used to sit in
        # the cache-miss branch: a cache hit skipped the model call and also
        # skipped the release, so the weights stayed resident for the rest of
        # the process -- and for the MLX backends, `unload` is what clears
        # the cache.
        active.unload()

    metadata = VideoMetadata(
        title=fields["title"],
        description=fields["description"],
        tags=list(fields["tags"]),
        chapters=list(chapters or []),
    )

    document = {
        "job_id": ctx.job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "prompt": version,
        "model": model_id,
        "platform": platform,
        "target_language": target_language,
        "metadata": {
            "title": metadata.title,
            "description": metadata.description,
            "tags": metadata.tags,
            "chapters": [
                {
                    "index": chapter.index,
                    "title": chapter.title,
                    "start_seconds": chapter.start_seconds,
                }
                for chapter in metadata.chapters
            ],
        },
    }
    path = ctx.jobs_dir / ctx.job_id / METADATA_FILENAME
    output_hash = artifacts.write_json(path, document)
    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-publishing-metadata",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(ctx.jobs_dir, ctx.job_id, path),
            input_hash=key,
            output_hash=output_hash,
            model=model_id,
            prompt_version=version,
        ),
    )

    duration_ms = int((time.perf_counter() - started) * 1000)
    with ulog.logging_context(job_id=ctx.job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="stage.completed",
            status="ok",
            duration_ms=duration_ms,
            platform=platform,
            model=model_id,
            cache_hit=cache_hit,
            tag_count=len(metadata.tags),
        )
    return MetadataResult(
        metadata=metadata,
        metadata_path=path,
        cache_hit=cache_hit,
        model=model_id,
        prompt_version=version,
    )


def load_metadata(path: str | Path) -> VideoMetadata:
    """Read metadata back from disk, for the publish command."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    payload = document.get("metadata")
    if not isinstance(payload, dict):
        raise PublishingMetadataError(f"{path} has no metadata block")
    tags = payload.get("tags") or []
    chapters = [
        Chapter(
            index=int(item["index"]),
            title=str(item["title"]),
            start_seconds=float(item["start_seconds"]),
        )
        for item in payload.get("chapters") or []
        if isinstance(item, dict)
    ]
    return VideoMetadata(
        title=str(payload.get("title") or ""),
        description=str(payload.get("description") or ""),
        tags=[str(tag) for tag in tags],
        chapters=chapters,
    )


def metadata_path(jobs_dir: str | Path, job_id: str) -> Path:
    """Where generated metadata is written for a job."""
    return Path(jobs_dir) / job_id / METADATA_FILENAME


def recorded_video_path(ctx: StageContext) -> Path | None:
    """The rendered video for a job, if the render stage has produced one.

    The renderer writes ``render/review.mp4`` at a fixed path -- the render
    manifest describes the timeline, not the output files -- so there is nothing
    to look up.
    """
    from movie_review.rendering.renderer import REVIEW_FILENAME
    from movie_review.rendering.renderer import STAGE_NAME as RENDER_STAGE

    candidate = ctx.jobs_dir / ctx.job_id / RENDER_STAGE / REVIEW_FILENAME
    return candidate if candidate.is_file() else None


def has_recorded_video(ctx: StageContext) -> bool:
    """True when a rendered video exists to publish."""
    return recorded_video_path(ctx) is not None
