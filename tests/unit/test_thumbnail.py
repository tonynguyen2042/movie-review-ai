"""T097 acceptance: thumbnail timestamp planning and extraction."""

from pathlib import Path

import pytest

from movie_review.domain import ManifestSegment, RenderManifest
from movie_review.media import frames as frame_sampler
from movie_review.publishing.thumbnail import (
    ThumbnailError,
    generate_thumbnail,
    plan_thumbnail,
    thumbnail_path,
)


def _manifest__thumbnail() -> RenderManifest:
    return RenderManifest(
        segments=[
            ManifestSegment(
                paragraph_id="p1",
                start=0.0,
                duration=60.0,
                scene_id="s1",
                clip_start=0.0,
                clip_end=5.0,
            ),
            ManifestSegment(
                paragraph_id="p2",
                start=60.0,
                duration=60.0,
                scene_id="s2",
                clip_start=0.0,
                clip_end=5.0,
            ),
            ManifestSegment(
                paragraph_id="p3",
                start=120.0,
                duration=60.0,
                scene_id="s3",
                clip_start=0.0,
                clip_end=5.0,
            ),
        ],
        total_seconds=180.0,
        source_seconds=45.0,
    )


def test_plan_thumbnail_picks_middle_segment_midpoint() -> None:
    """The default ratio lands inside the middle segment at its midpoint."""
    plan = plan_thumbnail(_manifest__thumbnail())
    assert plan.segment_id == "p2"
    assert plan.timestamp == 90.0
    assert plan.duration_seconds == 60.0


def test_plan_thumbnail_avoids_edges() -> None:
    """Extreme ratios are pulled inside the margin instead of the edges."""
    manifest = _manifest__thumbnail()
    low = plan_thumbnail(manifest, position_ratio=0.0)
    high = plan_thumbnail(manifest, position_ratio=1.0)
    margin = 180.0 * 0.05  # 9 seconds

    assert low.timestamp >= margin
    assert high.timestamp <= 180.0 - margin


def test_plan_thumbnail_honors_position_ratio() -> None:
    """Later ratios select later segments."""
    manifest = _manifest__thumbnail()
    early = plan_thumbnail(manifest, position_ratio=0.3)
    late = plan_thumbnail(manifest, position_ratio=0.7)
    assert early.segment_id == "p1"
    assert late.segment_id == "p3"
    assert early.timestamp < late.timestamp


def test_plan_thumbnail_varies_with_ratio_on_uneven_segments() -> None:
    """Ratios spread continuously instead of collapsing to one midpoint."""
    manifest = RenderManifest(
        segments=[
            ManifestSegment(
                paragraph_id="p1",
                start=0.0,
                duration=10.0,
                scene_id="s1",
                clip_start=0.0,
                clip_end=5.0,
            ),
            ManifestSegment(
                paragraph_id="p2",
                start=10.0,
                duration=100.0,
                scene_id="s2",
                clip_start=0.0,
                clip_end=5.0,
            ),
            ManifestSegment(
                paragraph_id="p3",
                start=110.0,
                duration=10.0,
                scene_id="s3",
                clip_start=0.0,
                clip_end=5.0,
            ),
        ],
        total_seconds=120.0,
        source_seconds=20.0,
    )
    stamps = [plan_thumbnail(manifest, position_ratio=r).timestamp for r in (0.25, 0.5, 0.75)]
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == 3


def test_plan_thumbnail_always_inside_chosen_segment() -> None:
    """The returned timestamp lies within the segment it reports."""
    manifest = RenderManifest(
        segments=[
            ManifestSegment(
                paragraph_id="p1",
                start=0.0,
                duration=10.0,
                scene_id="s1",
                clip_start=0.0,
                clip_end=5.0,
            ),
            ManifestSegment(
                paragraph_id="p2",
                start=50.0,
                duration=5.0,
                scene_id="s2",
                clip_start=0.0,
                clip_end=5.0,
            ),
        ],
        total_seconds=55.0,
        source_seconds=10.0,
    )
    for step in range(21):
        ratio = step / 20
        plan = plan_thumbnail(manifest, position_ratio=ratio)
        segment = next(s for s in manifest.segments if s.paragraph_id == plan.segment_id)
        assert segment.start <= plan.timestamp <= segment.start + segment.duration
        assert 0.0 <= plan.timestamp <= manifest.total_seconds


def test_plan_thumbnail_handles_gap_between_segments() -> None:
    """A target landing in a timeline gap still resolves to a real segment."""
    manifest = RenderManifest(
        segments=[
            ManifestSegment(
                paragraph_id="p1",
                start=0.0,
                duration=5.0,
                scene_id="s1",
                clip_start=0.0,
                clip_end=5.0,
            ),
            ManifestSegment(
                paragraph_id="p2",
                start=50.0,
                duration=5.0,
                scene_id="s2",
                clip_start=0.0,
                clip_end=5.0,
            ),
        ],
        total_seconds=55.0,
        source_seconds=10.0,
    )
    plan = plan_thumbnail(manifest, position_ratio=0.5)
    assert plan.segment_id in {"p1", "p2"}
    assert 0.0 <= plan.timestamp <= 55.0


def test_plan_thumbnail_rejects_empty_manifest() -> None:
    """An empty manifest is a classified failure."""
    empty = RenderManifest.model_construct(segments=[], total_seconds=0.0, source_seconds=0.0)
    with pytest.raises(ThumbnailError):
        plan_thumbnail(empty)


@pytest.mark.parametrize("ratio", [-0.1, 1.1])
def test_plan_thumbnail_rejects_bad_position_ratio(ratio: float) -> None:
    """An out-of-range position ratio is rejected."""
    with pytest.raises(ThumbnailError):
        plan_thumbnail(_manifest__thumbnail(), position_ratio=ratio)


@pytest.mark.parametrize("margin", [-0.1, 0.5, 0.9])
def test_plan_thumbnail_rejects_bad_edge_margin(margin: float) -> None:
    """An out-of-range edge margin is rejected."""
    with pytest.raises(ThumbnailError):
        plan_thumbnail(_manifest__thumbnail(), edge_margin_ratio=margin)


def test_generate_thumbnail_uses_injected_extractor(tmp_path: Path) -> None:
    """Extraction is delegated to the injected frame sampler."""
    dest = tmp_path / "thumb.jpg"
    dest.write_bytes(b"jpeg-bytes")
    calls: list[tuple[float, Path]] = []

    def fake_extract(source, timestamp, target, ffmpeg="ffmpeg"):
        calls.append((timestamp, Path(target)))
        return Path(target)

    result = generate_thumbnail("movie.mp4", _manifest__thumbnail(), dest, extract_fn=fake_extract)

    assert result.path == dest
    assert result.plan.timestamp == 90.0
    assert calls == [(90.0, dest)]


def test_generate_thumbnail_wraps_extraction_failure(tmp_path: Path) -> None:
    """Frame sampling failures surface as ThumbnailError."""

    def failing(source, timestamp, target, ffmpeg="ffmpeg"):
        raise frame_sampler.FrameSamplingError("no frame")

    with pytest.raises(ThumbnailError):
        generate_thumbnail(
            "movie.mp4", _manifest__thumbnail(), tmp_path / "t.jpg", extract_fn=failing
        )


def test_generate_thumbnail_rejects_missing_output(tmp_path: Path) -> None:
    """An extractor that writes nothing is a classified failure."""

    def no_output(source, timestamp, target, ffmpeg="ffmpeg"):
        return Path(target)

    with pytest.raises(ThumbnailError):
        generate_thumbnail(
            "movie.mp4", _manifest__thumbnail(), tmp_path / "absent.jpg", extract_fn=no_output
        )


def test_thumbnail_path_is_deterministic(tmp_path: Path) -> None:
    """The artifact path follows the standard job/stage/file layout."""
    path = thumbnail_path(tmp_path / "jobs", "job_1")
    assert path == tmp_path / "jobs" / "job_1" / "publishing" / "thumbnail.jpg"
