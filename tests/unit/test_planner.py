"""T041 acceptance: deterministic timed outlines over evidence."""

import pytest

from movie_review.domain import Event, EventType
from movie_review.review.planner import plan_review
from movie_review.review.styles import load_style


def _events() -> list[Event]:
    return [
        Event(
            id="e1",
            type=EventType.INTRODUCTION,
            timestamp=5.0,
            description="Arrival.",
            importance=0.4,
        ),
        Event(
            id="e2",
            type=EventType.MEETING,
            timestamp=15.0,
            characters=["char_001", "char_002"],
            description="Meet.",
            importance=0.6,
        ),
        Event(
            id="e3",
            type=EventType.BETRAYAL,
            timestamp=50.0,
            characters=["char_002"],
            description="Lies.",
            importance=0.85,
        ),
        Event(
            id="e4",
            type=EventType.CLIMAX,
            timestamp=90.0,
            characters=["char_001"],
            description="Showdown.",
            importance=0.97,
        ),
        Event(
            id="e5",
            type=EventType.RESOLUTION,
            timestamp=110.0,
            description="Peace.",
            importance=0.7,
        ),
    ]


def test_totals_match_target() -> None:
    plan = plan_review(_events(), load_style("youtube"))
    assert plan.total_seconds == 1200
    assert [s.type for s in plan.sections] == [
        "hook",
        "premise",
        "characters",
        "setup",
        "conflict",
        "revelations",
        "climax",
        "ending",
    ]
    short = plan_review(_events(), load_style("funny"), target_seconds=600)
    assert short.total_seconds == 600


def test_hook_and_climax_reference_top_events() -> None:
    plan = plan_review(_events(), load_style("youtube"))
    by_type = {s.type: s for s in plan.sections}
    assert by_type["hook"].event_ids == ["e4"]
    assert by_type["climax"].event_ids == ["e4"]
    assert set(by_type["premise"].event_ids) == {"e1", "e2"}
    assert "e5" in by_type["ending"].event_ids


def test_empty_events_still_structured() -> None:
    plan = plan_review([], load_style("youtube"))
    assert plan.total_seconds == 1200
    assert all(section.event_ids == [] for section in plan.sections)


def test_bad_target_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        plan_review(_events(), load_style("youtube"), target_seconds=0)


def test_deterministic() -> None:
    style = load_style("youtube")
    assert plan_review(_events(), style) == plan_review(_events(), style)
