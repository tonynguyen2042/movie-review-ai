"""Optional publishing support (Phase 12)."""

from movie_review.publishing.metadata import (
    Chapter,
    MetadataError,
    VideoMetadata,
    generate_metadata,
)
from movie_review.publishing.port import (
    PublishingError,
    PublishingPort,
    PublishingUnavailableError,
    UploadReceipt,
    UploadRejectedError,
    UploadRequest,
    VideoMetadataLike,
)
from movie_review.publishing.thumbnail import (
    ThumbnailError,
    ThumbnailPlan,
    ThumbnailResult,
    generate_thumbnail,
    plan_thumbnail,
)
from movie_review.publishing.youtube import YouTubeAdapter

__all__ = [
    "Chapter",
    "MetadataError",
    "PublishingError",
    "PublishingPort",
    "PublishingUnavailableError",
    "ThumbnailError",
    "ThumbnailPlan",
    "ThumbnailResult",
    "UploadReceipt",
    "UploadRejectedError",
    "UploadRequest",
    "VideoMetadata",
    "VideoMetadataLike",
    "YouTubeAdapter",
    "generate_metadata",
    "generate_thumbnail",
    "plan_thumbnail",
]
