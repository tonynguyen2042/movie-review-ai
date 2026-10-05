"""T065 acceptance: timeline alignment scoring."""

from movie_review.domain import Event, EventType, Scene
from movie_review.quality.timeline import timeline_consistency


def _event(event_id: str, timestamp: float) -> Event:
    return Event(id=event_id, type=EventType.ACTION, timestamp=timestamp, description="Something.")


def _scene(scene_id: str, start: float, end: float) -> Scene:
    return Scene(scene_id=scene_id, start=start, end=end, duration=end - start)


def test_full_alignment() -> None:
    metric = timeline_consistency([_event("e1", 5.0)], [_scene("s1", 0.0, 10.0)])
    assert metric.name == "timeline_consistency"
    assert metric.score == 100.0


def test_partial_alignment() -> None:
    metric = timeline_consistency(
        [_event("e1", 5.0), _event("e2", 50.0)], [_scene("s1", 0.0, 10.0)]
    )
    assert metric.score == 50.0
    assert "e2" in metric.detail


def test_vacuous() -> None:
    assert timeline_consistency([], [_scene("s1", 0.0, 10.0)]).score == 100.0


def test_boundary_end_exclusive() -> None:
    metric = timeline_consistency([_event("e1", 10.0)], [_scene("s1", 0.0, 10.0)])
    assert metric.score == 0.0
