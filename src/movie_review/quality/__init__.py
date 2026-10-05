"""Quality metrics, gates, and reports (T063-T069)."""

from movie_review.quality.characters import character_consistency
from movie_review.quality.coverage import evidence_coverage
from movie_review.quality.gates import (
    GATE_THRESHOLDS,
    MAX_DURATION_ERROR,
    GateResult,
    QualityGateError,
    duration_metric,
    evaluate_gate,
    run_quality_gate,
)
from movie_review.quality.report import QualityReportResult, build_quality_report
from movie_review.quality.timeline import timeline_consistency
from movie_review.quality.visual import visual_alignment

__all__ = [
    "GATE_THRESHOLDS",
    "MAX_DURATION_ERROR",
    "GateResult",
    "QualityGateError",
    "QualityReportResult",
    "build_quality_report",
    "character_consistency",
    "duration_metric",
    "evaluate_gate",
    "evidence_coverage",
    "run_quality_gate",
    "timeline_consistency",
    "visual_alignment",
]
