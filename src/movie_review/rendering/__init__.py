"""Visual planning and FFmpeg rendering (T056 planner, T057 clips)."""

from movie_review.domain import VisualPlan
from movie_review.rendering.clips import (
    ClipSelectionError,
    SelectedClip,
    cut_window,
    select_clips,
)
from movie_review.rendering.planner import paragraph_claim_refs, plan_visuals

__all__ = [
    "ClipSelectionError",
    "SelectedClip",
    "VisualPlan",
    "cut_window",
    "paragraph_claim_refs",
    "plan_visuals",
    "select_clips",
]
