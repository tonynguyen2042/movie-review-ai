"""Script repair loop applying fact-check verdicts (T049, spec section 33).

Deterministic claim-level repairs: contradicted claims are removed,
insufficiently evidenced factual claims become labeled interpretation, and
partially supported claims are qualified in place. Prose rewriting needs an
LLM pass and stays explicitly out of scope: repaired prose keeps its shape,
only claim records change.
"""

from __future__ import annotations

from dataclasses import dataclass

from movie_review.domain import ClaimStatus, ClaimType, ReviewScript
from movie_review.review.factcheck import ClaimVerdict

_QUALIFIER = "Reportedly, "


class RepairError(Exception):
    """Repair failed in a classified way (verdict/script mismatch)."""


@dataclass(frozen=True)
class RepairResult:
    """Repaired script plus applied-change counts."""

    script: ReviewScript
    removed: int
    converted: int
    qualified: int


def _qualify(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    if stripped.lower().startswith("reportedly"):
        return stripped
    return _QUALIFIER + stripped[0].lower() + stripped[1:]


def repair_script(script: ReviewScript, verdicts: list[ClaimVerdict]) -> RepairResult:
    """Apply verdicts to a script copy; unknown IDs raise :class:`RepairError`."""
    by_id = {verdict.claim_id: verdict for verdict in verdicts}
    known = {
        claim.claim_id
        for section in script.sections
        for paragraph in section.paragraphs
        for claim in paragraph.claims
    }
    unknown = [claim_id for claim_id in by_id if claim_id not in known]
    if unknown:
        raise RepairError(f"Verdicts for unknown claims: {unknown}")

    removed = converted = qualified = 0
    sections = []
    for section in script.sections:
        paragraphs = []
        for paragraph in section.paragraphs:
            claims = []
            for claim in paragraph.claims:
                verdict = by_id.get(claim.claim_id)
                if verdict is None:
                    claims.append(claim)
                    continue
                if verdict.status is ClaimStatus.CONTRADICTED:
                    removed += 1
                    continue
                if verdict.status is ClaimStatus.INSUFFICIENT_EVIDENCE and (
                    claim.type not in (ClaimType.INTERPRETATION, ClaimType.OPINION, ClaimType.THEME)
                ):
                    converted += 1
                    claims.append(
                        claim.model_copy(update={"type": ClaimType.INTERPRETATION, "evidence": []})
                    )
                    continue
                if verdict.status is ClaimStatus.PARTIALLY_SUPPORTED:
                    qualified += 1
                    claims.append(claim.model_copy(update={"text": _qualify(claim.text)}))
                    continue
                claims.append(claim)
            paragraphs.append(paragraph.model_copy(update={"claims": claims}))
        sections.append(section.model_copy(update={"paragraphs": paragraphs}))
    repaired = script.model_copy(update={"sections": sections})
    return RepairResult(script=repaired, removed=removed, converted=converted, qualified=qualified)
