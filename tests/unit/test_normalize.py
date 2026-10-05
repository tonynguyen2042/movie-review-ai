"""T019 acceptance: timestamp-preserving transcript normalization."""

from movie_review.asr.normalize import normalize_segments, normalize_text
from movie_review.domain import TranscriptSegment


def _segment(segment_id: str, start: float, end: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(segment_id=segment_id, start=start, end=end, text=text)


def test_normalize_text_collapses_whitespace() -> None:
    assert normalize_text("  hello\t\n  world  ") == "hello world"


def test_normalize_text_unicode() -> None:
    assert normalize_text("Ｈｅｌｌｏ") == "Hello"
    assert normalize_text("ﬁlm") == "film"


def test_normalize_text_drops_controls() -> None:
    assert normalize_text("a\x00b\x07c") == "abc"
    assert normalize_text("   ") == ""


def test_normalize_segments_drops_empties_by_default() -> None:
    segments = [
        _segment("seg_00001", 2.0, 3.0, "  second  "),
        _segment("seg_00000", 0.0, 1.0, "   "),
    ]
    result = normalize_segments(segments)
    assert [s.segment_id for s in result] == ["seg_00001"]
    assert result[0].text == "second"
    assert (result[0].start, result[0].end) == (2.0, 3.0)


def test_normalize_segments_keeps_empties_when_asked() -> None:
    segments = [_segment("seg_00000", 0.0, 1.0, "")]
    result = normalize_segments(segments, drop_empty=False)
    assert len(result) == 1
    assert result[0].segment_id == "seg_00000"


def test_normalize_segments_sorts_by_start() -> None:
    segments = [
        _segment("b", 5.0, 6.0, "b"),
        _segment("a", 1.0, 2.0, "a"),
    ]
    assert [s.segment_id for s in normalize_segments(segments)] == ["a", "b"]
