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


@dataclass(frozen=True)
class EvidenceIndex:
    """The evidence pool for a job, with its text, resolved once.

    The pool used to be rebuilt for every candidate: each dialogue candidate
    re-read the whole transcript and then scanned it for its own segment. The
    statement count was therefore ``3 + n_segments + n_events +
    n_characters`` for a single retrieval, and the fact checker ran one
    retrieval per claim. Building the pool once turns that into
    ``O(segments + events + characters)`` for the whole script.

    It also carries the ids a claim's references are resolved against, so
    the fact checker's dangling-reference check does not re-read the
    transcript for every reference either.
    """

    candidates: list[Evidence]
    texts: dict[str, str]
    known_ids: set[str]
    segment_texts: dict[str, str]


def build_index(conn: sqlite3.Connection, job_id: str) -> EvidenceIndex:
    """Resolve every candidate and its text in one pass."""
    candidates: list[Evidence] = []
    texts: dict[str, str] = {}
    known_ids: set[str] = set()
    segment_texts: dict[str, str] = {}

    for segment in repo.list_transcript_segments(conn, job_id):
        evidence = Evidence(
            id=f"ret-{segment.segment_id}",
            type=EvidenceType.DIALOGUE,
            source_id=segment.segment_id,
            start=segment.start,
            end=segment.end,
            confidence=segment.confidence,
        )
        candidates.append(evidence)
        texts[evidence.id] = segment.text
        known_ids.add(segment.segment_id)
        segment_texts[segment.segment_id] = segment.text

    for event in repo.list_events(conn, job_id):
        evidence = Evidence(
            id=f"ret-{event.id}",
            type=EvidenceType.EVENT,
            source_id=event.id,
            start=event.timestamp,
            end=event.timestamp,
            confidence=event.importance,
        )
        candidates.append(evidence)
        texts[evidence.id] = event.description
        known_ids.add(event.id)

    for character in repo.list_characters(conn, job_id):
        evidence = Evidence(
            id=f"ret-{character.id}",
            type=EvidenceType.CHARACTER,
            source_id=character.id,
            confidence=character.confidence,
        )
        candidates.append(evidence)
        texts[evidence.id] = f"{character.name} {' '.join(character.aliases)}"
        known_ids.add(character.id)

    for scene in repo.list_scenes(conn, job_id):
        known_ids.add(scene.scene_id)

    return EvidenceIndex(
        candidates=candidates,
        texts=texts,
        known_ids=known_ids,
        segment_texts=segment_texts,
    )


def retrieve_evidence(
    claim_text: str,
    conn: sqlite3.Connection,
    job_id: str,
    limit: int = 5,
    index: EvidenceIndex | None = None,
) -> list[RetrievedEvidence]:
    """Rank knowledge coverage of a claim; empty pool yields [].

    ``index`` lets a caller that scores many claims build the pool once.
    """
    wanted = _terms(claim_text)
    if not wanted:
        return []
    active = index if index is not None else build_index(conn, job_id)
    scored: list[RetrievedEvidence] = []
    for candidate in active.candidates:
        text = active.texts.get(candidate.id, "")
        if not text.strip():
            continue
        overlap = wanted & _terms(text)
        if overlap:
            scored.append(RetrievedEvidence(candidate, len(overlap) / len(wanted)))
    scored.sort(key=lambda item: (-item.score, item.evidence.source_id))
    return scored[: max(1, limit)]
