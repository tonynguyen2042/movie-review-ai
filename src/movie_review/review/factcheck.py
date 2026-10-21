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
from movie_review.review.retrieval import EvidenceIndex, build_index, retrieve_evidence

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


def _resolves(index: EvidenceIndex, ref: str) -> bool:
    """Whether a claim's reference names something the job actually has.

    The index carries the ids of every segment, event, character and scene,
    so the check is a set lookup. It used to be four queries per reference,
    one of them a full transcript read.
    """
    return ref in index.known_ids


def _dialogue_texts(index: EvidenceIndex, refs: list[str]) -> list[str]:
    return [index.segment_texts[ref] for ref in refs if ref in index.segment_texts]


def _misquoted(claim_text: str, dialogue_texts: list[str]) -> bool:
    """True when a quoted line appears in none of the cited segments.

    A quote is misquoted when it is absent from *every* cited segment. The
    previous form asked whether any quote matched any segment, so a claim
    quoting two lines was judged clean as long as one of them was real --
    which is exactly the case a fabricated quotation takes.
    """
    quotes = [normalize_text(q).lower() for q in _QUOTED_RE.findall(claim_text) if q.strip()]
    if not quotes or not dialogue_texts:
        return False
    haystacks = [normalize_text(text).lower() for text in dialogue_texts]
    return any(all(quote not in haystack for haystack in haystacks) for quote in quotes)


def check_claim(
    claim: Claim,
    conn: sqlite3.Connection,
    job_id: str,
    index: EvidenceIndex | None = None,
) -> ClaimVerdict:
    """Verify one claim; never upgrades uncertainty without evidence.

    ``index`` lets a caller that checks many claims resolve the evidence
    pool once instead of once per claim.
    """
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
    active = index if index is not None else build_index(conn, job_id)
    dangling = [ref for ref in claim.evidence if not _resolves(active, ref)]
    if dangling:
        return ClaimVerdict(
            claim_id=claim.claim_id,
            status=ClaimStatus.INSUFFICIENT_EVIDENCE,
            evidence=list(claim.evidence),
            reasons=[f"dangling references: {dangling}"],
        )
    if claim.type is ClaimType.DIALOGUE_REFERENCE and _misquoted(
        claim.text, _dialogue_texts(active, claim.evidence)
    ):
        return ClaimVerdict(
            claim_id=claim.claim_id,
            status=ClaimStatus.CONTRADICTED,
            evidence=list(claim.evidence),
            reasons=["quoted dialogue absent from cited segments"],
        )
    top = retrieve_evidence(claim.text, conn, job_id, limit=1, index=index)
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
    """Verify claims in order.

    The evidence pool is built once for the whole script. It used to be
    rebuilt for every claim, and each rebuild re-read the entire transcript
    once per candidate -- so a script with sixty claims cost sixty times the
    transcript, per claim.
    """
    index = build_index(conn, job_id)
    return [check_claim(claim, conn, job_id, index=index) for claim in claims]
