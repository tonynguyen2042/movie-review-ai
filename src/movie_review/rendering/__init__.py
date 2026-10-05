"""Visual planning, rendering, manifest, subtitles, audio, renderer, validation (T056-T062)."""

from movie_review.domain import VisualPlan
from movie_review.rendering.audio import MixError, MixResult, mix
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
from movie_review.rendering.renderer import (
    REVIEW_FILENAME,
    RenderError,
    RenderResult,
    render,
    render_job,
)
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
from movie_review.rendering.validate import (
    RenderValidationError,
    ValidationCheck,
    ValidationReport,
    validate_render,
)

__all__ = [
    "ClipSelectionError",
    "ManifestError",
    "ManifestResult",
    "MixError",
    "MixResult",
    "REVIEW_FILENAME",
    "RenderError",
    "RenderResult",
    "SelectedClip",
    "SubtitleCue",
    "SubtitleError",
    "RenderValidationError",
    "ValidationCheck",
    "ValidationReport",
    "VisualPlan",
    "assemble_manifest",
    "build_cues",
    "build_manifest",
    "cut_window",
    "format_srt",
    "format_timestamp",
    "mix",
    "paragraph_claim_refs",
    "parse_srt",
    "parse_timestamp",
    "plan_visuals",
    "render",
    "render_job",
    "select_clips",
    "validate_render",
    "write_srt",
]
