"""Visual planning, rendering, and manifest (T056 planner, T057 clips, T058 manifest)."""

from movie_review.domain import VisualPlan
from movie_review.rendering.clips import (
    ClipSelectionError,
    SelectedClip,
    cut_window,
    select_clips,
)
from movie_review.rendering.manifest import (
    ManifestError,
    ManifestResult,
    assemble_manifest,
    build_manifest,
)
from movie_review.rendering.planner import paragraph_claim_refs, plan_visuals

__all__ = [
    "ClipSelectionError",
    "ManifestError",
    "ManifestResult",
    "SelectedClip",
    "VisualPlan",
    "assemble_manifest",
    "build_manifest",
    "cut_window",
    "paragraph_claim_refs",
    "plan_visuals",
    "select_clips",
]
