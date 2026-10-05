"""Evidence registry: deduped registration and source lookup (T034, FR-010).

The evidence table (T005) stores rows; the registry adds write semantics:
registering the same ``(type, source_id)`` twice keeps the highest
confidence instead of duplicating. Retrieval (T046) and fact checking (T047)
build on these queries.
"""

from __future__ import annotations

import sqlite3

from movie_review.domain import Evidence, EvidenceType
from movie_review.storage import repositories as repo


def register_evidence(conn: sqlite3.Connection, job_id: str, evidence: Evidence) -> bool:
    """Register evidence, keeping the highest confidence on duplicates.

    Returns True when a new row was created or confidence improved.
    """
    existing = [
        item
        for item in repo.list_evidence(conn, job_id, evidence.type)
        if item.source_id == evidence.source_id
    ]
    if existing:
        best = max(existing, key=lambda item: item.confidence)
        if best.confidence >= evidence.confidence:
            return False
        evidence = evidence.model_copy(update={"id": best.id})
    repo.save_evidence(conn, job_id, evidence)
    return True


def find_by_source(conn: sqlite3.Connection, job_id: str, source_id: str) -> list[Evidence]:
    """All evidence pointing at one source (segment, scene, event...)."""
    return [item for item in repo.list_evidence(conn, job_id) if item.source_id == source_id]


def find_by_type(conn: sqlite3.Connection, job_id: str, type: EvidenceType) -> list[Evidence]:
    """All evidence of one type."""
    return repo.list_evidence(conn, job_id, type)
