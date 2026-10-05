"""Theme extraction from ordered events (T037, README section 25).

Artifact-only extraction like story arcs: no job-lifecycle transition (the
STORY_READY milestone belongs to the T039 assembly). Uses the shared
reasoning port and the T037 prompt.
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
from movie_review.domain import Artifact, Event, Theme
from movie_review.reasoning.port import ReasoningPort
from movie_review.reasoning.qwen import QwenReasoningAdapter
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "story"
STAGE_VERSION = "v1"
THEMES_FILENAME = "themes.json"
MAX_EVENTS = 100


class ThemeExtractionError(Exception):
    """Theme extraction failed in a classified way."""


@dataclass
class ThemesResult:
    """Outcome of one theme extraction run."""

    themes: list[Theme]
    themes_path: Path
    cache_hit: bool


def extract_themes(
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
) -> ThemesResult:
    """Extract grounded themes; persists ``themes.json``."""
    if not events:
        raise ThemeExtractionError("Event extraction must run before themes")
    prompt = load_prompt("theme", prompt_version)
    active = reasoner or QwenReasoningAdapter(model)
    model_id = active.model if isinstance(active, QwenReasoningAdapter) else type(active).__name__

    selected = sorted(events, key=lambda e: (-e.importance, e.timestamp))[:MAX_EVENTS]
    selected = sorted(selected, key=lambda e: e.timestamp)
    event_lines = "\n".join(
        f"{event.id} [{event.type.value} @ {event.timestamp:.1f}]: {event.description}"
        for event in selected
    )
    text = render(prompt, events=event_lines, characters=characters or "none yet")
    spec = CacheSpec(
        stage="themes",
        stage_version=STAGE_VERSION,
        input_hash=artifacts.sha256_bytes(event_lines.encode("utf-8")),
        model_id=model_id,
        prompt_version=f"{prompt.name}:{prompt.version}",
    )
    key = cache_key(spec)
    cached = cache.lookup_json(key)
    if cached is not None:
        if not isinstance(cached, list):
            raise ThemeExtractionError("Cached themes are corrupt")
        raw = cached
        cache_hit = True
    else:
        try:
            raw = active.complete_json(text)
        except Exception as exc:
            raise ThemeExtractionError(f"Cannot extract themes: {exc}") from exc
        finally:
            active.unload()
        if not isinstance(raw, list):
            raise ThemeExtractionError("Expected theme array")
        cache.store_json(key, raw)
        cache_hit = False

    themes = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ThemeExtractionError("Malformed theme entry")
        try:
            theme = Theme.model_validate(entry)
        except ValueError as exc:
            raise ThemeExtractionError(f"Invalid theme: {exc}") from exc
        if not theme.evidence:
            raise ThemeExtractionError(f"Theme {theme.theme!r} cites no evidence")
        themes.append(theme)

    document = {
        "job_id": job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "prompt": f"{prompt.name}:{prompt.version}",
        "model": model_id,
        "themes": [theme.model_dump(mode="json") for theme in themes],
    }
    themes_path = artifacts.artifact_path(jobs_dir, job_id, STAGE_NAME, THEMES_FILENAME)
    output_hash = artifacts.write_json(themes_path, document)
    repo.save_artifact(
        conn,
        Artifact(
            artifact_id=f"{job_id}-themes",
            job_id=job_id,
            stage=STAGE_NAME,
            input_hash=key,
            output_hash=output_hash,
            model=model_id,
            prompt_version=f"{prompt.name}:{prompt.version}",
        ),
    )
    with ulog.logging_context(job_id=job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="themes.completed",
            status="ok",
            cache_hit=cache_hit,
            themes=len(themes),
        )
    return ThemesResult(themes=themes, themes_path=themes_path, cache_hit=cache_hit)
