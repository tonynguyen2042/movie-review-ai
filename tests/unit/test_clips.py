"""T057 acceptance: exact ranges honoring per-clip limits."""

import pytest

from movie_review.domain import Event, EventType, Scene
from movie_review.rendering.clips import (
    ClipSelectionError,
    cut_window,
    select_clips,
)
from tests.helpers import (
    _paragraph,
)


def _scene__clips() -> Scene:
    return Scene(scene_id="scene_000001", start=10.0, end=30.0, duration=20.0)


def test_cut_window_centered() -> None:
    assert cut_window(_scene__clips(), 20.0, 3.0, 8.0) == (18.5, 21.5)


def test_cut_window_clamped_to_edges() -> None:
    assert cut_window(_scene__clips(), 11.0, 3.0, 8.0) == (10.0, 13.0)
    assert cut_window(_scene__clips(), 29.0, 3.0, 8.0) == (27.0, 30.0)


def test_cut_window_short_scene() -> None:
    short = Scene(scene_id="s", start=0.0, end=1.0, duration=1.0)
    assert cut_window(short, 0.5, 3.0, 8.0) == (0.0, 1.0)


def test_cut_window_bad_limit() -> None:
    with pytest.raises(ClipSelectionError, match="clip limit"):
        cut_window(_scene__clips(), 20.0, 3.0, 0.0)


def _events__clips() -> list[Event]:
    return [
        Event(id="event_00001", type=EventType.MEETING, timestamp=15.0, description="Meet."),
    ]


def test_select_centers_on_event() -> None:
    [clip] = select_clips(
        [_paragraph("p1", "event_00001")],
        {"p1": "scene_000001"},
        [_scene__clips()],
        _events__clips(),
    )
    assert (clip.start, clip.end) == (13.5, 16.5)
    assert clip.duration == pytest.approx(3.0)


def test_select_defaults_to_middle() -> None:
    [clip] = select_clips(
        [_paragraph("p1")], {"p1": "scene_000001"}, [_scene__clips()], _events__clips()
    )
    assert (clip.start, clip.end) == (18.5, 21.5)


def test_select_missing_plan_or_scene() -> None:
    with pytest.raises(ClipSelectionError, match="No planned scene"):
        select_clips([_paragraph("p1")], {}, [_scene__clips()], _events__clips())
    with pytest.raises(ClipSelectionError, match="Unknown scene"):
        select_clips([_paragraph("p1")], {"p1": "ghost"}, [_scene__clips()], _events__clips())


def test_select_respects_max() -> None:
    [clip] = select_clips(
        [_paragraph("p1", "event_00001")],
        {"p1": "scene_000001"},
        [_scene__clips()],
        _events__clips(),
        max_clip_seconds=2.0,
        preferred_seconds=3.0,
    )
    assert clip.duration == pytest.approx(2.0)
