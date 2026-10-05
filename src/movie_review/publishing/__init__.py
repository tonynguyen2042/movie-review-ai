"""Optional publishing support (Phase 12)."""

from movie_review.publishing.metadata import (
    DESCRIPTION_MAX_CHARS,
    MAX_TAGS,
    TITLE_MAX_CHARS,
    Chapter,
    MetadataError,
    VideoMetadata,
    build_chapters,
    build_description,
    build_tags,
    build_title,
    generate_metadata,
    script_text,
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
    DEFAULT_EDGE_MARGIN_RATIO,
    THUMBNAIL_FILENAME,
    ThumbnailError,
    ThumbnailPlan,
    ThumbnailResult,
    generate_thumbnail,
    plan_thumbnail,
    thumbnail_path,
)
from movie_review.publishing.thumbnail import (
    STAGE_NAME as THUMBNAIL_STAGE_NAME,
)
from movie_review.publishing.thumbnail import (
    STAGE_VERSION as THUMBNAIL_STAGE_VERSION,
)
from movie_review.publishing.youtube import (
    DEFAULT_CATEGORY_ID,
    PRIVACY_STATES,
    RawUpload,
    YouTubeAdapter,
)

__all__ = [
    "DEFAULT_CATEGORY_ID",
    "DEFAULT_EDGE_MARGIN_RATIO",
    "DESCRIPTION_MAX_CHARS",
    "MAX_TAGS",
    "PRIVACY_STATES",
    "THUMBNAIL_FILENAME",
    "THUMBNAIL_STAGE_NAME",
    "THUMBNAIL_STAGE_VERSION",
    "TITLE_MAX_CHARS",
    "Chapter",
    "MetadataError",
    "PublishingError",
    "PublishingPort",
    "PublishingUnavailableError",
    "RawUpload",
    "ThumbnailError",
    "ThumbnailPlan",
    "ThumbnailResult",
    "UploadReceipt",
    "UploadRejectedError",
    "UploadRequest",
    "VideoMetadata",
    "VideoMetadataLike",
    "YouTubeAdapter",
    "build_chapters",
    "build_description",
    "build_tags",
    "build_title",
    "generate_metadata",
    "generate_thumbnail",
    "plan_thumbnail",
    "script_text",
    "thumbnail_path",
]
