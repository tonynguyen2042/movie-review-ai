"""Evidence coverage evaluation (T082, spec acceptance 10).

Fraction of major claims carrying at least one evidence reference that
exists in the analysis registry. Target: at least 90% on the golden set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MIN_EVIDENCE_COVERAGE = 90.0

MAJOR_CLAIM_TYPES = frozenset({"PLOT_FACT", "CHARACTER_FACT", "TIMELINE_FACT"})


@dataclass(frozen=True)
class CoverageEvalReport:
    """Coverage summary over major claims."""

    major_total: int
    covered: int
    coverage: float

    @property
    def passed(self) -> bool:
        """True when coverage meets the target, or there was nothing to score.

        A claim set with no major claims (e.g. an opinion-only review) is not
        penalised; that intent is pinned by ``test_coverage_ignores_opinion``.
        The reported ``coverage`` value is still honest in that case -- 0.0,
        meaning unmeasured -- rather than a fabricated 100.0.
        """
        if self.major_total == 0:
            return True
        return self.coverage >= MIN_EVIDENCE_COVERAGE


def evaluate_coverage(claims: list[dict[str, Any]], evidence_ids: list[str]) -> CoverageEvalReport:
    """Score major claims with at least one known evidence reference.

    ``coverage`` is ``0.0`` when there are no major claims -- reporting 100.0
    there would assert a measurement that never happened.
    """
    known = set(evidence_ids)
    major = [claim for claim in claims if claim.get("type") in MAJOR_CLAIM_TYPES]
    covered = sum(1 for claim in major if any(ref in known for ref in claim.get("evidence", [])))
    coverage = (100.0 * covered / len(major)) if major else 0.0
    return CoverageEvalReport(major_total=len(major), covered=covered, coverage=coverage)
