"""T056 acceptance: evidence-priority visual mapping."""

from movie_review.domain import (
    Event,
    EventType,
    ReviewParagraph,
    ReviewScript,
    ReviewSection,
    Scene,
    SceneAnalysis,
)
from movie_review.rendering.planner import plan_visuals
from tests.helpers import (
    _paragraph,
    _scene,
)


def _script__visual_planner(*paragraphs: ReviewParagraph) -> ReviewScript:
    return ReviewScript(
        sections=[ReviewSection(id="sec_01", type="hook", paragraphs=list(paragraphs))]
    )


def _scenes__visual_planner() -> list[Scene]:
    return [_scene("scene_000001", 0.0, 10.0), _scene("scene_000002", 10.0, 20.0)]


def _events__visual_planner() -> list[Event]:
    return [
        Event(
            id="event_00001",
            type=EventType.MEETING,
            timestamp=5.0,
            characters=["char_001"],
            description="Meet.",
        ),
    ]


def _analyses__visual_planner() -> dict[str, SceneAnalysis]:
    return {
        "scene_000001": SceneAnalysis(scene_id="scene_000001", characters=["char_001"]),
        "scene_000002": SceneAnalysis(scene_id="scene_000002", characters=["char_001", "char_002"]),
    }


def test_direct_scene_ref_first() -> None:
    plan = plan_visuals(
        _script__visual_planner(_paragraph("p1", "scene_000002")),
        _scenes__visual_planner(),
        _analyses__visual_planner(),
        _events__visual_planner(),
    )
    [clip] = plan.paragraph_clips
    assert (clip.scene_id, clip.priority, clip.reason) == (
        "scene_000002",
        1,
        "direct evidence clip",
    )


def test_event_ref_maps_to_scene_plus_reaction() -> None:
    plan = plan_visuals(
        _script__visual_planner(_paragraph("p1", "event_00001")),
        _scenes__visual_planner(),
        _analyses__visual_planner(),
        _events__visual_planner(),
    )
    assert [(c.scene_id, c.priority) for c in plan.paragraph_clips] == [
        ("scene_000001", 1),
        ("scene_000002", 2),
    ]
    assert plan.paragraph_clips[1].reason == "character reaction"


def test_location_context_tier() -> None:
    scenes = _scenes__visual_planner() + [_scene("scene_000003", 20.0, 30.0)]
    analyses = {
        **_analyses__visual_planner(),
        "scene_000001": SceneAnalysis(scene_id="scene_000001", location="Dock"),
        "scene_000003": SceneAnalysis(scene_id="scene_000003", location="Dock"),
    }
    plan = plan_visuals(
        _script__visual_planner(_paragraph("p1", "event_00001")),
        scenes,
        analyses,
        _events__visual_planner(),
    )
    by_scene = {c.scene_id: c for c in plan.paragraph_clips}
    assert by_scene["scene_000003"].reason == "location context"
    assert by_scene["scene_000003"].priority == 3


def test_object_tier() -> None:
    scenes = _scenes__visual_planner() + [_scene("scene_000003", 20.0, 30.0)]
    analyses = {
        "scene_000001": SceneAnalysis(scene_id="scene_000001", objects=["photograph"]),
        "scene_000002": SceneAnalysis(scene_id="scene_000002"),
        "scene_000003": SceneAnalysis(scene_id="scene_000003", objects=["photograph"]),
    }
    plan = plan_visuals(
        _script__visual_planner(_paragraph("p1", "event_00001")),
        scenes,
        analyses,
        _events__visual_planner(),
    )
    by_scene = {c.scene_id: c for c in plan.paragraph_clips}
    assert by_scene["scene_000003"].reason == "relevant object"


def test_no_refs_falls_back_to_establishing() -> None:
    plan = plan_visuals(
        _script__visual_planner(_paragraph("p1")),
        _scenes__visual_planner(),
        _analyses__visual_planner(),
        _events__visual_planner(),
    )
    [clip] = plan.paragraph_clips
    assert (clip.scene_id, clip.reason) == ("scene_000001", "establishing fallback")


def test_unknown_refs_fall_back() -> None:
    plan = plan_visuals(
        _script__visual_planner(_paragraph("p1", "ghost")),
        _scenes__visual_planner(),
        _analyses__visual_planner(),
        _events__visual_planner(),
    )
    assert [c.scene_id for c in plan.paragraph_clips] == ["scene_000001"]


def test_all_paragraphs_covered() -> None:
    plan = plan_visuals(
        _script__visual_planner(_paragraph("p1", "scene_000001"), _paragraph("p2", "scene_000002")),
        _scenes__visual_planner(),
        _analyses__visual_planner(),
        _events__visual_planner(),
    )
    assert {c.paragraph_id for c in plan.paragraph_clips} == {"p1", "p2"}
