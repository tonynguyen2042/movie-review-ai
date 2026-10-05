"""Visual planning, rendering, manifest, and subtitles (T056-T059)."""

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
from movie_review.rendering.subtitles import (
    SubtitleCue,
    SubtitleError,
    build_cues,
    format_srt,
    format_timestamp,
    parse_srt,
    parse_timestamp,
    write_srt,
)

__all__ = [
    "ClipSelectionError",
    "ManifestError",
    "ManifestResult",
    "SelectedClip",
    "SubtitleCue",
    "SubtitleError",
    "VisualPlan",
    "assemble_manifest",
    "build_cues",
    "build_manifest",
    "cut_window",
    "format_srt",
    "format_timestamp",
    "paragraph_claim_refs",
    "parse_srt",
    "parse_timestamp",
    "plan_visuals",
    "select_clips",
    "write_srt",
]
