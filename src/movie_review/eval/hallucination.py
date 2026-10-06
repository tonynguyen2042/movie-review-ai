"""Hallucination evaluation (T081, spec acceptance 9).

Flags major claims (PLOT/CHARACTER/TIMELINE facts) whose verdict is
CONTRADICTED or INSUFFICIENT_EVIDENCE. Unsupported-major rate must stay
below 2% on the golden set; interpretation/opinion claims are excluded
since they are explicitly marked as such.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAJOR_CLAIM_TYPES = frozenset({"PLOT_FACT", "CHARACTER_FACT", "TIMELINE_FACT"})
BAD_VERDICTS = frozenset({"CONTRADICTED", "INSUFFICIENT_EVIDENCE"})

MAX_UNSUPPORTED_MAJOR_RATE = 0.02


@dataclass(frozen=True)
class HallucinationReport:
    """Unsupported-major-claim summary."""

    major_total: int
    unsupported: int
    unsupported_ids: list[str]
    rate: float

    @property
    def passed(self) -> bool:
        """True while unsupported majors stay under the threshold.

        A claim set with no major claims (e.g. an opinion-only review)
        reports ``passed``. That is deliberate: interpretation and opinion
        are explicitly excluded from this metric, so there is nothing to
        penalise. Pinned by ``test_hallucination_ignores_opinion``.
        """
        return self.rate < MAX_UNSUPPORTED_MAJOR_RATE


def evaluate_hallucinations(claims: list[dict[str, Any]]) -> HallucinationReport:
    """Score major-claim support from claim dicts with type/verdict keys."""
    major = [claim for claim in claims if claim.get("type") in MAJOR_CLAIM_TYPES]
    bad = [claim for claim in major if claim.get("verdict") in BAD_VERDICTS]
    rate = len(bad) / len(major) if major else 0.0
    return HallucinationReport(
        major_total=len(major),
        unsupported=len(bad),
        unsupported_ids=[str(claim.get("claim_id", "?")) for claim in bad],
        rate=rate,
    )
