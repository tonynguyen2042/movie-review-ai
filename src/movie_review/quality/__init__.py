"""Quality metrics and gates (T063 model, T064-T067 metrics)."""

from movie_review.quality.characters import character_consistency
from movie_review.quality.coverage import evidence_coverage
from movie_review.quality.timeline import timeline_consistency
from movie_review.quality.visual import visual_alignment

__all__ = [
    "character_consistency",
    "evidence_coverage",
    "timeline_consistency",
    "visual_alignment",
]
