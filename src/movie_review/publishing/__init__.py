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

__all__ = [
    "DESCRIPTION_MAX_CHARS",
    "MAX_TAGS",
    "TITLE_MAX_CHARS",
    "Chapter",
    "MetadataError",
    "VideoMetadata",
    "build_chapters",
    "build_description",
    "build_tags",
    "build_title",
    "generate_metadata",
    "script_text",
]
