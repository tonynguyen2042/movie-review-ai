"""Character discovery from VLM analyses and dialogue (T028, FR-007).

Deterministic and offline: candidates come from VLM-listed characters,
quoted dialogue spans, and multi-word capitalized phrases. Nothing is
guessed — confidence reflects source count and diversity, and identity
linking happens later (T029).
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field

from movie_review.asr.normalize import normalize_text
from movie_review.domain import Character, CharacterMention, SceneAnalysis, TranscriptSegment
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

_QUOTED_RE = re.compile(r'"([^"]{1,60})"')
_PHRASE_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
_STOPWORDS = frozenset({"I", "We", "You", "He", "She", "It", "They"})


class CharacterDiscoveryError(Exception):
    """Character discovery failed in a classified way."""


@dataclass
class _Candidate:
    name: str
    first_seen: float
    last_seen: float
    scene_ids: set[str] = field(default_factory=set)
    segment_ids: set[str] = field(default_factory=set)

    def observe(self, timestamp: float, end: float) -> None:
        self.first_seen = min(self.first_seen, timestamp)
        self.last_seen = max(self.last_seen, end)


@dataclass(frozen=True)
class DiscoveryResult:
    """Discovered characters plus their dialogue mentions."""

    characters: list[Character]
    mentions: list[CharacterMention]


def _key(name: str) -> str:
    return normalize_text(name).lower()


def _valid_name(name: str) -> bool:
    cleaned = normalize_text(name)
    return bool(cleaned) and cleaned not in _STOPWORDS and len(cleaned) <= 60


def discover_characters(
    analyses: list[SceneAnalysis],
    scene_spans: dict[str, tuple[float, float]],
    segments: list[TranscriptSegment],
) -> DiscoveryResult:
    """Collect character candidates from analyses and dialogue mentions."""
    candidates: dict[str, _Candidate] = {}

    def _add(name: str, start: float, end: float) -> None:
        if not _valid_name(name):
            return
        key = _key(name)
        candidate = candidates.get(key)
        if candidate is None:
            candidate = _Candidate(name=normalize_text(name), first_seen=start, last_seen=end)
            candidates[key] = candidate
        else:
            candidate.observe(start, end)

    for analysis in analyses:
        span = scene_spans.get(analysis.scene_id)
        if span is None:
            continue
        for name in analysis.characters:
            if not _valid_name(name):
                continue
            _add(name, span[0], span[1])
            candidates[_key(name)].scene_ids.add(analysis.scene_id)

    for segment in segments:
        quoted = _QUOTED_RE.findall(segment.text)
        phrases = _PHRASE_RE.findall(segment.text)
        for name in quoted + phrases:
            if not _valid_name(name):
                continue
            _add(name, segment.start, segment.end)
            candidates[_key(name)].segment_ids.add(segment.segment_id)

    ordered = sorted(candidates.values(), key=lambda c: (c.first_seen, c.name))
    characters: list[Character] = []
    ids: dict[str, str] = {}
    for index, candidate in enumerate(ordered, start=1):
        character_id = f"char_{index:03d}"
        ids[_key(candidate.name)] = character_id
        sources = len(candidate.scene_ids) + len(candidate.segment_ids)
        confidence = min(0.5 + 0.1 * sources, 0.9)
        characters.append(
            Character(
                id=character_id,
                name=candidate.name,
                first_seen=candidate.first_seen,
                last_seen=candidate.last_seen,
                confidence=confidence,
            )
        )

    starts = {segment.segment_id: segment.start for segment in segments}
    mentions = [
        CharacterMention(
            mention=candidate.name,
            source_segment_id=segment_id,
            timestamp=starts[segment_id],
            character_id=ids[_key(candidate.name)],
        )
        for candidate in ordered
        for segment_id in sorted(candidate.segment_ids)
    ]
    with ulog.logging_context(stage="characters"):
        ulog.log_event(
            _logger, event="discovery.completed", status="ok", characters=len(characters)
        )
    return DiscoveryResult(characters=characters, mentions=mentions)


def save_discovery(conn: sqlite3.Connection, job_id: str, result: DiscoveryResult) -> None:
    """Persist discovery output through the T027 repositories."""
    # Every AI output passes schema validation before it enters the next
    # stage (README section 6.6).
    from movie_review.schemas import SchemaError, validate_artifact

    for character in result.characters:
        try:
            validate_artifact("character", character.model_dump(mode="json"))
        except SchemaError as exc:
            raise CharacterDiscoveryError(str(exc)) from exc

    for character in result.characters:
        repo.save_character(conn, job_id, character)
    # One transaction for every mention: a mention is written once per
    # (character, segment) pair, and each write was its own commit.
    repo.save_mentions(conn, job_id, result.mentions)
