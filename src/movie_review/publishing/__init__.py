"""Optional publishing support (Phase 12)."""

from movie_review.publishing.ai_metadata import (
    EVIDENCE_MARKER,
    METADATA_FILENAME,
    NARRATION_EXCERPT_CHARS,
    MetadataResult,
    PublishingMetadataError,
    UnsupportedClaimError,
    generate_publishing_metadata,
    load_metadata,
    metadata_path,
    narration_excerpt,
    recorded_video_path,
)
from movie_review.publishing.facebook import (
    GRAPH_API_VERSION,
    FacebookPageAdapter,
    PageUpload,
)
from movie_review.publishing.facebook import (
    VISIBILITIES as FACEBOOK_VISIBILITIES,
)
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
from movie_review.publishing.registry import (
    PLATFORMS,
    build_adapter,
    is_platform,
    platform_names,
    unavailable_reason,
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
from movie_review.publishing.tiktok import (
    APP_REVIEW_NOTICE,
    TikTokAdapter,
    TikTokUpload,
)
from movie_review.publishing.tiktok import (
    DEFAULT_PRIVACY_LEVEL as TIKTOK_PRIVACY_LEVEL,
)
from movie_review.publishing.youtube import (
    DEFAULT_CATEGORY_ID,
    PRIVACY_STATES,
    RawUpload,
    YouTubeAdapter,
)

__all__ = [
    "APP_REVIEW_NOTICE",
    "DEFAULT_CATEGORY_ID",
    "DEFAULT_EDGE_MARGIN_RATIO",
    "DESCRIPTION_MAX_CHARS",
    "EVIDENCE_MARKER",
    "FACEBOOK_VISIBILITIES",
    "GRAPH_API_VERSION",
    "MAX_TAGS",
    "METADATA_FILENAME",
    "NARRATION_EXCERPT_CHARS",
    "PLATFORMS",
    "PRIVACY_STATES",
    "THUMBNAIL_FILENAME",
    "THUMBNAIL_STAGE_NAME",
    "THUMBNAIL_STAGE_VERSION",
    "TIKTOK_PRIVACY_LEVEL",
    "TITLE_MAX_CHARS",
    "Chapter",
    "FacebookPageAdapter",
    "MetadataError",
    "MetadataResult",
    "PageUpload",
    "PublishingError",
    "PublishingMetadataError",
    "PublishingPort",
    "PublishingUnavailableError",
    "RawUpload",
    "ThumbnailError",
    "ThumbnailPlan",
    "ThumbnailResult",
    "TikTokAdapter",
    "TikTokUpload",
    "UnsupportedClaimError",
    "UploadReceipt",
    "UploadRejectedError",
    "UploadRequest",
    "VideoMetadata",
    "VideoMetadataLike",
    "YouTubeAdapter",
    "build_adapter",
    "build_chapters",
    "build_description",
    "build_tags",
    "build_title",
    "generate_metadata",
    "generate_publishing_metadata",
    "generate_thumbnail",
    "is_platform",
    "load_metadata",
    "metadata_path",
    "narration_excerpt",
    "plan_thumbnail",
    "platform_names",
    "recorded_video_path",
    "script_text",
    "thumbnail_path",
    "unavailable_reason",
]
