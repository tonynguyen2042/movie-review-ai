"""T059 acceptance: timing-derived cues with SRT round-trip."""

from pathlib import Path

import pytest

from movie_review.domain import ManifestSegment, RenderManifest
from movie_review.rendering.subtitles import (
    SubtitleError,
    build_cues,
    format_srt,
    format_timestamp,
    parse_srt,
    parse_timestamp,
    split_text,
    write_srt,
)


def _manifest() -> RenderManifest:
    return RenderManifest(
        segments=[
            ManifestSegment(
                paragraph_id="p1",
                start=0.0,
                duration=10.0,
                scene_id="s1",
                clip_start=0.0,
                clip_end=5.0,
                loop_clip=True,
            ),
            ManifestSegment(
                paragraph_id="p2",
                start=10.0,
                duration=20.0,
                scene_id="s2",
                clip_start=3.0,
                clip_end=6.0,
            ),
        ],
        total_seconds=30.0,
        source_seconds=8.0,
    )


def test_timestamps() -> None:
    assert format_timestamp(0.0) == "00:00:00,000"
    assert format_timestamp(61.5) == "00:01:01,500"
    assert format_timestamp(3661.001) == "01:01:01,001"
    assert parse_timestamp("00:01:01,500") == pytest.approx(61.5)
    with pytest.raises(SubtitleError, match="Invalid SRT timestamp"):
        parse_timestamp("not-a-time")


def test_split_text() -> None:
    text = " ".join(f"word{n}" for n in range(40))
    chunks = split_text(text)
    assert all(len(chunk) <= 84 for chunk in chunks)
    assert " ".join(chunks) == text
    assert split_text("   ") == []


def test_build_cues_tiles_spans() -> None:
    cues = build_cues(_manifest(), {"p1": "Short text here.", "p2": "Other words here."})
    assert [(c.start, c.end) for c in cues] == [(0.0, 10.0), (10.0, 30.0)]
    assert [c.index for c in cues] == [1, 2]


def test_build_cues_splits_long_text() -> None:
    long_text = " ".join(f"word{n}" for n in range(60))
    cues = build_cues(_manifest(), {"p1": long_text, "p2": ""})
    assert len(cues) > 1
    assert cues[0].start == 0.0
    assert cues[-1].end == pytest.approx(10.0)
    assert all(second.start == first.end for first, second in zip(cues, cues[1:], strict=False))


def test_srt_round_trip() -> None:
    cues = build_cues(_manifest(), {"p1": "Hello.", "p2": "World."})
    text = format_srt(cues)
    assert text.startswith("1\n00:00:00,000 --> 00:00:10,000\nHello.")
    assert parse_srt(text) == cues
    assert format_srt([]) == ""


def test_parse_malformed() -> None:
    with pytest.raises(SubtitleError):
        parse_srt("1\nno-arrow-here\ntext")
    with pytest.raises(SubtitleError):
        parse_srt("oops")


def test_write_srt(tmp_path: Path) -> None:
    cues = build_cues(_manifest(), {"p1": "Hello."})
    path = write_srt(tmp_path / "sub" / "review.srt", cues)
    assert path.is_file()
    assert parse_srt(path.read_text(encoding="utf-8")) == cues
