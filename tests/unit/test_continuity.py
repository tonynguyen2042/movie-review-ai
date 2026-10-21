"""T048 acceptance: death consistency and reference integrity."""

from movie_review.domain import EventType, Scene
from movie_review.review.continuity import check_continuity
from tests.helpers import (
    _event,
)


def _scene__continuity(scene_id: str) -> Scene:
    return Scene(scene_id=scene_id, start=0.0, end=1.0, duration=1.0)


def test_clean_passes() -> None:
    events = [
        _event("e1", EventType.MEETING, 5.0, ["char_001"]),
        _event("e2", EventType.DEATH, 50.0, ["char_002"], ["scene_000001"]),
    ]
    assert check_continuity(events, [_scene__continuity("scene_000001")]) == []


def test_activity_after_death_flagged() -> None:
    events = [
        _event("e1", EventType.DEATH, 50.0, ["char_001"]),
        _event("e2", EventType.ACTION, 60.0, ["char_001"]),
        _event("e3", EventType.ACTION, 60.0, ["char_002"]),
    ]
    [issue] = check_continuity(events, [])
    assert issue.kind == "character-active-after-death"
    assert issue.subject == "char_001"
    assert "e1" in issue.detail


def test_flashback_exempt() -> None:
    events = [
        _event("e1", EventType.DEATH, 50.0, ["char_001"]),
        _event("e2", EventType.FLASHBACK, 60.0, ["char_001"]),
    ]
    assert check_continuity(events, []) == []


def test_dangling_scene_ref_flagged() -> None:
    events = [_event("e1", EventType.MEETING, 5.0, evidence=["scene_999999"])]
    [issue] = check_continuity(events, [_scene__continuity("scene_000001")])
    assert issue.kind == "dangling-scene-ref"
    assert issue.subject == "e1"
