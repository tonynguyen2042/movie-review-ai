"""Optional publishing support (Phase 12)."""

from movie_review.publishing.thumbnail import (
    DEFAULT_EDGE_MARGIN_RATIO,
    ThumbnailError,
    ThumbnailPlan,
    ThumbnailResult,
    generate_thumbnail,
    plan_thumbnail,
    thumbnail_path,
)

__all__ = [
    "DEFAULT_EDGE_MARGIN_RATIO",
    "ThumbnailError",
    "ThumbnailPlan",
    "ThumbnailResult",
    "generate_thumbnail",
    "plan_thumbnail",
    "thumbnail_path",
]
