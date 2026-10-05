"""Fact checking of review claims against knowledge (T047, spec section 33).

Deterministic and offline: cited references must resolve, retrieval coverage
must clear thresholds, and quoted dialogue must match its cited segment
(the v1 contradiction rule). No NLI models; verdicts a judge cannot support
stay conservative (partial/insufficient over supported).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from movie_review.asr.normalize import normalize_text
from movie_review.domain import Claim, ClaimStatus, ClaimType
from movie_review.review.retrieval import retrieve_evidence
from movie_review.storage import repositories as repo

_QUOTED_RE = re.compile(r'"([^"]+)"')

SUPPORT_COVERAGE = 0.5
NON_FACTUAL = frozenset({ClaimType.INTERPRETATION, ClaimType.OPINION, ClaimType.THEME})


@dataclass(frozen=True)
class ClaimVerdict:
    """One claim's verification outcome."""

    claim_id: str
    status: ClaimStatus
    evidence: list[str]
    reasons: list[str] = field(default_factory=list)


def _resolves(conn: sqlite3.Connection, job_id: str, ref: str) -> bool:
    if repo.get_event(conn, job_id, ref) is not None:
        return True
    if repo.get_character(conn, job_id, ref) is not None:
        return True
    if repo.get_scene(conn, job_id, ref) is not None:
        return True
    segments = repo.list_transcript_segments(conn, job_id)
    return any(segment.segment_id == ref for segment in segments)


def _dialogue_texts(conn: sqlite3.Connection, job_id: str, refs: list[str]) -> list[str]:
    segments = {s.segment_id: s.text for s in repo.list_transcript_segments(conn, job_id)}
    return [segments[ref] for ref in refs if ref in segments]


def _misquoted(claim_text: str, dialogue_texts: list[str]) -> bool:
    quotes = [normalize_text(q).lower() for q in _QUOTED_RE.findall(claim_text) if q.strip()]
    if not quotes or not dialogue_texts:
        return False
    haystacks = [normalize_text(text).lower() for text in dialogue_texts]
    return not any(quote in haystack for quote in quotes for haystack in haystacks)


def check_claim(claim: Claim, conn: sqlite3.Connection, job_id: str) -> ClaimVerdict:
    """Verify one claim; never upgrades uncertainty without evidence."""
    if claim.type in NON_FACTUAL:
        return ClaimVerdict(
            claim_id=claim.claim_id,
            status=ClaimStatus.SUPPORTED,
            evidence=list(claim.evidence),
            reasons=["not fact-checkable by design"],
        )
    if not claim.evidence:
        return ClaimVerdict(
            claim_id=claim.claim_id,
            status=ClaimStatus.INSUFFICIENT_EVIDENCE,
            evidence=[],
            reasons=["no evidence cited"],
        )
    dangling = [ref for ref in claim.evidence if not _resolves(conn, job_id, ref)]
    if dangling:
        return ClaimVerdict(
            claim_id=claim.claim_id,
            status=ClaimStatus.INSUFFICIENT_EVIDENCE,
            evidence=list(claim.evidence),
            reasons=[f"dangling references: {dangling}"],
        )
    if claim.type is ClaimType.DIALOGUE_REFERENCE and _misquoted(
        claim.text, _dialogue_texts(conn, job_id, claim.evidence)
    ):
        return ClaimVerdict(
            claim_id=claim.claim_id,
            status=ClaimStatus.CONTRADICTED,
            evidence=list(claim.evidence),
            reasons=["quoted dialogue absent from cited segments"],
        )
    top = retrieve_evidence(claim.text, conn, job_id, limit=1)
    coverage = top[0].score if top else 0.0
    if coverage >= SUPPORT_COVERAGE:
        status = ClaimStatus.SUPPORTED
    elif coverage > 0.0:
        status = ClaimStatus.PARTIALLY_SUPPORTED
    else:
        status = ClaimStatus.INSUFFICIENT_EVIDENCE
    return ClaimVerdict(
        claim_id=claim.claim_id,
        status=status,
        evidence=list(claim.evidence),
        reasons=[f"retrieval coverage {coverage:.2f}"],
    )


def check_claims(claims: list[Claim], conn: sqlite3.Connection, job_id: str) -> list[ClaimVerdict]:
    """Verify claims in order."""
    return [check_claim(claim, conn, job_id) for claim in claims]
