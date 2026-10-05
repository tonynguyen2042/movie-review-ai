"""Claim extraction from review scripts (T045, spec sections 32-33).

Validates writer-produced claims into stable :class:`Claim` records for fact
checking (T047). Writer IDs are preserved for traceability; missing IDs get
deterministic paragraph-scoped fallbacks. Duplicate IDs are rejected loudly.
"""

from __future__ import annotations

import sqlite3

from movie_review.domain import Claim, ReviewScript
from movie_review.storage import repositories as repo


class ClaimExtractionError(Exception):
    """Claim extraction failed in a classified way."""


def extract_claims(script: ReviewScript) -> list[Claim]:
    """Collect and validate every claim in document order."""
    claims: list[Claim] = []
    seen: set[str] = set()
    for section in script.sections:
        for paragraph in section.paragraphs:
            for position, raw in enumerate(paragraph.claims):
                claim_id = raw.claim_id or f"{paragraph.id}-c{position + 1}"
                if claim_id in seen:
                    raise ClaimExtractionError(f"Duplicate claim ID: {claim_id}")
                seen.add(claim_id)
                if not raw.text.strip():
                    raise ClaimExtractionError(f"Empty claim text: {claim_id}")
                claims.append(
                    Claim(
                        claim_id=claim_id,
                        text=raw.text,
                        type=raw.type,
                        evidence=list(raw.evidence),
                        confidence=raw.confidence,
                    )
                )
    return claims


def store_claims(conn: sqlite3.Connection, job_id: str, claims: list[Claim]) -> None:
    """Persist extracted claims through the T005 repository."""
    for claim in claims:
        repo.save_claim(conn, job_id, claim)
