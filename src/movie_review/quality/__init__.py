"""Quality metrics and gates (T063 model, T064 coverage, T065 timeline)."""

from movie_review.quality.coverage import evidence_coverage
from movie_review.quality.timeline import timeline_consistency

__all__ = ["evidence_coverage", "timeline_consistency"]
