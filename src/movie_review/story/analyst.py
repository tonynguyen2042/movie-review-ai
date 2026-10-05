"""Story analyst agent toolkit and brief composer (T042, README section 61).

Query tools over persisted knowledge for story reasoning. Tools never
invent evidence: missing entities return None/[] (README section 62), and
the brief marks absent sections explicitly.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.domain import (
    Character,
    Event,
    Evidence,
    Scene,
    TranscriptSegment,
)
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoryBrief:
    """Deterministic story summary for planners and writers."""

    job_id: str
    character_count: int
    event_count: int
    span_seconds: float
    protagonists: list[str] = field(default_factory=list)
    pivotal_events: list[str] = field(default_factory=list)
    arc_elements: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    has_twists: bool = False


class StoryAnalyst:
    """Agent tools: get_character/scene/dialogue/event/evidence + search."""

    def __init__(
        self, conn: sqlite3.Connection, job_id: str, jobs_dir: str | Path | None = None
    ) -> None:
        self._conn = conn
        self._job_id = job_id
        self._jobs_dir = Path(jobs_dir) if jobs_dir is not None else None

    def get_character(self, character_id: str) -> Character | None:
        """Character record or None when no evidence exists."""
        return repo.get_character(self._conn, self._job_id, character_id)

    def get_scene(self, scene_id: str) -> Scene | None:
        """Scene record or None when no evidence exists."""
        return repo.get_scene(self._conn, self._job_id, scene_id)

    def get_dialogue(self, start: float, end: float) -> list[TranscriptSegment]:
        """Transcript segments overlapping ``[start, end)`` (possibly empty)."""
        return [
            segment
            for segment in repo.list_transcript_segments(self._conn, self._job_id)
            if segment.start < end and segment.end > start
        ]

    def get_event(self, event_id: str) -> Event | None:
        """Event record or None when no evidence exists."""
        return repo.get_event(self._conn, self._job_id, event_id)

    def get_evidence(self, source_id: str) -> list[Evidence]:
        """Evidence pointing at one source (possibly empty)."""
        from movie_review.knowledge.registry import find_by_source

        return find_by_source(self._conn, self._job_id, source_id)

    def search_story(self, query: str, limit: int = 10) -> list[Event]:
        """Lexical event search over descriptions (no vector DB per P17)."""
        terms = [term.lower() for term in query.split() if term]
        if not terms:
            return []
        scored = []
        for event in repo.list_events(self._conn, self._job_id):
            haystack = f"{event.description} {event.type.value}".lower()
            hits = sum(1 for term in terms if term in haystack)
            if hits:
                scored.append((hits, event.importance, event))
        scored.sort(key=lambda item: (-item[0], -item[1]))
        return [event for _, _, event in scored[: max(1, limit)]]

    def _story_file(self, filename: str, key: str) -> list[object]:
        if self._jobs_dir is None:
            return []
        path = self._jobs_dir / self._job_id / "story" / filename
        if not path.is_file():
            return []
        try:
            document = artifacts.read_json(path)
        except (OSError, ValueError):
            return []
        if not isinstance(document, dict):
            return []
        entries = document.get(key, [])
        return entries if isinstance(entries, list) else []

    def analyze(self) -> StoryBrief:
        """Compose a brief from characters, events, and story artifacts."""
        characters = repo.list_characters(self._conn, self._job_id)
        events = repo.list_events(self._conn, self._job_id)
        participation: dict[str, int] = {}
        for event in events:
            for character_id in event.characters:
                participation[character_id] = participation.get(character_id, 0) + 1
        protagonists = sorted(participation, key=lambda cid: (-participation[cid], cid))[:3]
        pivotal = sorted(events, key=lambda e: (-e.importance, e.timestamp))[:3]
        span = max((event.timestamp for event in events), default=0.0)
        arcs = self._story_file("story-arcs.json", "arcs")
        themes = self._story_file("themes.json", "themes")
        twists = self._story_file("twists.json", "twists")
        with ulog.logging_context(job_id=self._job_id, stage="story"):
            ulog.log_event(_logger, event="analysis.completed", status="ok")
        return StoryBrief(
            job_id=self._job_id,
            character_count=len(characters),
            event_count=len(events),
            span_seconds=span,
            protagonists=protagonists,
            pivotal_events=[event.id for event in pivotal],
            arc_elements=[
                str(entry["element"])
                for entry in arcs
                if isinstance(entry, dict) and entry.get("applicable", True)
            ],
            themes=[
                str(entry["theme"])
                for entry in themes
                if isinstance(entry, dict) and "theme" in entry
            ],
            has_twists=len(twists) > 0,
        )
