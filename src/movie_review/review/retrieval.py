"""Evidence retrieval for claim verification (T046, spec sections 59-60).

Deterministic lexical retrieval over persisted knowledge: transcript
segments, events, and character names. No vector database (P17); SQLite FTS
tables remain a future optimization if measurements demand it.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from movie_review.domain import Evidence, EvidenceType
from movie_review.storage import repositories as repo

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "was",
        "were",
        "are",
        "be",
        "been",
        "it",
        "he",
        "she",
        "they",
        "we",
        "you",
        "i",
        "his",
        "her",
        "their",
        "and",
        "or",
        "but",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "with",
        "that",
        "this",
        "these",
        "those",
        "not",
        "no",
        "so",
        "as",
        "by",
    }
)


@dataclass(frozen=True)
class RetrievedEvidence:
    """One candidate with its coverage score in [0, 1]."""

    evidence: Evidence
    score: float


def _terms(text: str) -> set[str]:
    return {word for word in _WORD_RE.findall(text.lower()) if word not in _STOPWORDS}


def _candidates(conn: sqlite3.Connection, job_id: str) -> list[Evidence]:
    found: list[Evidence] = []
    for segment in repo.list_transcript_segments(conn, job_id):
        found.append(
            Evidence(
                id=f"ret-{segment.segment_id}",
                type=EvidenceType.DIALOGUE,
                source_id=segment.segment_id,
                start=segment.start,
                end=segment.end,
                confidence=segment.confidence,
            )
        )
    for event in repo.list_events(conn, job_id):
        found.append(
            Evidence(
                id=f"ret-{event.id}",
                type=EvidenceType.EVENT,
                source_id=event.id,
                start=event.timestamp,
                end=event.timestamp,
                confidence=event.importance,
            )
        )
    for character in repo.list_characters(conn, job_id):
        found.append(
            Evidence(
                id=f"ret-{character.id}",
                type=EvidenceType.CHARACTER,
                source_id=character.id,
                confidence=character.confidence,
            )
        )
    return found


def _candidate_text(evidence: Evidence, conn: sqlite3.Connection, job_id: str) -> str:
    if evidence.type is EvidenceType.DIALOGUE:
        segments = repo.list_transcript_segments(conn, job_id)
        return next((s.text for s in segments if s.segment_id == evidence.source_id), "")
    if evidence.type is EvidenceType.EVENT:
        event = repo.get_event(conn, job_id, evidence.source_id)
        return event.description if event else ""
    if evidence.type is EvidenceType.CHARACTER:
        character = repo.get_character(conn, job_id, evidence.source_id)
        if character is None:
            return ""
        return f"{character.name} {' '.join(character.aliases)}"
    return ""


def retrieve_evidence(
    claim_text: str, conn: sqlite3.Connection, job_id: str, limit: int = 5
) -> list[RetrievedEvidence]:
    """Rank knowledge coverage of a claim; empty pool yields []."""
    wanted = _terms(claim_text)
    if not wanted:
        return []
    scored: list[RetrievedEvidence] = []
    for candidate in _candidates(conn, job_id):
        text = _candidate_text(candidate, conn, job_id)
        if not text.strip():
            continue
        overlap = wanted & _terms(text)
        if overlap:
            scored.append(RetrievedEvidence(candidate, len(overlap) / len(wanted)))
    scored.sort(key=lambda item: (-item.score, item.evidence.source_id))
    return scored[: max(1, limit)]
