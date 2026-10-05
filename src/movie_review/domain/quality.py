"""Quality control models (spec section 68).

Scores run 0-100. Each metric carries its own pass threshold; the report
passes only when every metric passes. Gate thresholds live in T068.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class QualityMetric(BaseModel):
    """One named quality measurement."""

    name: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=100.0)
    threshold: float = Field(ge=0.0, le=100.0, default=0.0)
    detail: str = ""

    @property
    def passed(self) -> bool:
        """True when the score meets the threshold."""
        return self.score >= self.threshold


class QualityReport(BaseModel):
    """Full quality verdict for a job."""

    job_id: str = Field(min_length=1)
    metrics: list[QualityMetric] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def overall(self) -> float:
        """Mean score (0 when no metrics)."""
        if not self.metrics:
            return 0.0
        return sum(metric.score for metric in self.metrics) / len(self.metrics)

    @property
    def passed(self) -> bool:
        """True only when every metric passes (vacuously false when empty)."""
        return bool(self.metrics) and all(metric.passed for metric in self.metrics)

    def failures(self) -> list[QualityMetric]:
        """Failing metrics only."""
        return [metric for metric in self.metrics if not metric.passed]
