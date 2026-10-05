"""Thumbnail generation (T097, spec Phase 12).

Selects a thumbnail timestamp from the render manifest and extracts a JPEG
frame through the FFmpeg adapter. Timestamp selection is pure domain logic so
it is testable without FFmpeg; extraction is injected for the same reason.

Copyright note (AGENTS.md): selecting a source frame is not a legal safety
determination, and nothing here claims fixed clip duration or percentage is
automatically safe to publish.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.domain import ManifestSegment, RenderManifest
from movie_review.media import frames as frame_sampler

_logger = logging.getLogger(__name__)

STAGE_NAME = "publishing"
STAGE_VERSION = "v1"
THUMBNAIL_FILENAME = "thumbnail.jpg"

# A thumbnail must avoid the first/last moments: black frames and end titles.
DEFAULT_EDGE_MARGIN_RATIO = 0.05


class ThumbnailError(Exception):
    """Thumbnail generation failed in a classified way."""


@dataclass(frozen=True)
class ThumbnailPlan:
    """Chosen thumbnail timestamp and its provenance."""

    timestamp: float
    segment_id: str
    duration_seconds: float


@dataclass(frozen=True)
class ThumbnailResult:
    """Extracted thumbnail with the plan that produced it."""

    path: Path
    plan: ThumbnailPlan


def _segment_at(segments: list[ManifestSegment], target: float) -> ManifestSegment:
    """Return the segment containing ``target``, else the nearest one."""
    containing = [
        segment
        for segment in segments
        if segment.start <= target <= segment.start + segment.duration
    ]
    if containing:
        return containing[0]
    return min(
        segments,
        key=lambda segment: min(
            abs(target - segment.start),
            abs(target - (segment.start + segment.duration)),
        ),
    )


def plan_thumbnail(
    manifest: RenderManifest,
    position_ratio: float = 0.5,
    edge_margin_ratio: float = DEFAULT_EDGE_MARGIN_RATIO,
) -> ThumbnailPlan:
    """Pick the midpoint of the segment at ``position_ratio`` of the timeline.

    Args:
        manifest: assembled render manifest.
        position_ratio: where in the total timeline to look, clamped to (0, 1).
        edge_margin_ratio: fraction of total duration skipped at both ends so
            the frame avoids fades and end titles.

    Raises:
        ThumbnailError: when the manifest has no usable segments or the
            ratio is out of range.
    """
    if not manifest.segments:
        raise ThumbnailError("Cannot plan a thumbnail from an empty manifest")
    if not 0.0 <= position_ratio <= 1.0:
        raise ThumbnailError(f"position_ratio must be within 0..1: {position_ratio}")
    if not 0.0 <= edge_margin_ratio < 0.5:
        raise ThumbnailError(f"edge_margin_ratio must be within 0..0.5: {edge_margin_ratio}")

    total = manifest.total_seconds
    if total <= 0:
        raise ThumbnailError(f"Manifest has non-positive duration: {total}")

    margin = total * edge_margin_ratio
    low, high = margin, total - margin
    if high < low:
        low, high = 0.0, total
    target = low + (high - low) * position_ratio

    chosen = _segment_at(manifest.segments, target)
    segment_end = chosen.start + chosen.duration
    # Clamp rather than snap to the midpoint so position_ratio stays meaningful
    # when segments are uneven.
    timestamp = min(max(target, chosen.start), segment_end, total)
    return ThumbnailPlan(
        timestamp=round(timestamp, 3),
        segment_id=chosen.paragraph_id,
        duration_seconds=chosen.duration,
    )


def generate_thumbnail(
    source: str | Path,
    manifest: RenderManifest,
    dest: str | Path,
    *,
    position_ratio: float = 0.5,
    edge_margin_ratio: float = DEFAULT_EDGE_MARGIN_RATIO,
    ffmpeg: str = "ffmpeg",
    extract_fn: Callable[..., Path] = frame_sampler.extract_frame,
) -> ThumbnailResult:
    """Plan a thumbnail timestamp and extract that frame as a JPEG.

    Raises:
        ThumbnailError: when planning fails or the frame is not produced.
    """
    plan = plan_thumbnail(manifest, position_ratio, edge_margin_ratio)
    try:
        path = extract_fn(source, plan.timestamp, dest, ffmpeg=ffmpeg)
    except frame_sampler.FrameSamplingError as exc:
        raise ThumbnailError(f"Thumbnail extraction failed: {exc}") from exc

    if not Path(path).is_file():
        raise ThumbnailError(f"Thumbnail extraction produced no file at {plan.timestamp}s")

    _logger.info(
        "thumbnail.generated",
        extra={"timestamp": plan.timestamp, "segment_id": plan.segment_id},
    )
    return ThumbnailResult(path=Path(path), plan=plan)


def thumbnail_path(jobs_dir: str | Path, job_id: str) -> Path:
    """Deterministic artifact path for one job's thumbnail."""
    return artifacts.artifact_path(jobs_dir, job_id, STAGE_NAME, THUMBNAIL_FILENAME)
