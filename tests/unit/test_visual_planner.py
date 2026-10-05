"""T056 acceptance: evidence-priority visual mapping."""

from movie_review.domain import (
    Claim,
    ClaimType,
    Event,
    EventType,
    ReviewParagraph,
    ReviewScript,
    ReviewSection,
    Scene,
    SceneAnalysis,
)
from movie_review.rendering.planner import plan_visuals


def _scene(scene_id: str, start: float, end: float) -> Scene:
    return Scene(scene_id=scene_id, start=start, end=end, duration=end - start)


def _paragraph(paragraph_id: str, *refs: str) -> ReviewParagraph:
    return ReviewParagraph(
        id=paragraph_id,
        text="Narration here.",
        target_seconds=12,
        claims=[
            Claim(
                claim_id=f"{paragraph_id}c{i}",
                text="Fact.",
                type=ClaimType.PLOT_FACT,
                evidence=[ref],
            )
            for i, ref in enumerate(refs)
        ],
        visual_intent="shot",
    )


def _script(*paragraphs: ReviewParagraph) -> ReviewScript:
    return ReviewScript(
        sections=[ReviewSection(id="sec_01", type="hook", paragraphs=list(paragraphs))]
    )


def _scenes() -> list[Scene]:
    return [_scene("scene_000001", 0.0, 10.0), _scene("scene_000002", 10.0, 20.0)]


def _events() -> list[Event]:
    return [
        Event(
            id="event_00001",
            type=EventType.MEETING,
            timestamp=5.0,
            characters=["char_001"],
            description="Meet.",
        ),
    ]


def _analyses() -> dict[str, SceneAnalysis]:
    return {
        "scene_000001": SceneAnalysis(scene_id="scene_000001", characters=["char_001"]),
        "scene_000002": SceneAnalysis(scene_id="scene_000002", characters=["char_001", "char_002"]),
    }


def test_direct_scene_ref_first() -> None:
    plan = plan_visuals(
        _script(_paragraph("p1", "scene_000002")), _scenes(), _analyses(), _events()
    )
    [clip] = plan.paragraph_clips
    assert (clip.scene_id, clip.priority, clip.reason) == (
        "scene_000002",
        1,
        "direct evidence clip",
    )


def test_event_ref_maps_to_scene_plus_reaction() -> None:
    plan = plan_visuals(_script(_paragraph("p1", "event_00001")), _scenes(), _analyses(), _events())
    assert [(c.scene_id, c.priority) for c in plan.paragraph_clips] == [
        ("scene_000001", 1),
        ("scene_000002", 2),
    ]
    assert plan.paragraph_clips[1].reason == "character reaction"


def test_location_context_tier() -> None:
    scenes = _scenes() + [_scene("scene_000003", 20.0, 30.0)]
    analyses = {
        **_analyses(),
        "scene_000001": SceneAnalysis(scene_id="scene_000001", location="Dock"),
        "scene_000003": SceneAnalysis(scene_id="scene_000003", location="Dock"),
    }
    plan = plan_visuals(_script(_paragraph("p1", "event_00001")), scenes, analyses, _events())
    by_scene = {c.scene_id: c for c in plan.paragraph_clips}
    assert by_scene["scene_000003"].reason == "location context"
    assert by_scene["scene_000003"].priority == 3


def test_object_tier() -> None:
    scenes = _scenes() + [_scene("scene_000003", 20.0, 30.0)]
    analyses = {
        "scene_000001": SceneAnalysis(scene_id="scene_000001", objects=["photograph"]),
        "scene_000002": SceneAnalysis(scene_id="scene_000002"),
        "scene_000003": SceneAnalysis(scene_id="scene_000003", objects=["photograph"]),
    }
    plan = plan_visuals(_script(_paragraph("p1", "event_00001")), scenes, analyses, _events())
    by_scene = {c.scene_id: c for c in plan.paragraph_clips}
    assert by_scene["scene_000003"].reason == "relevant object"


def test_no_refs_falls_back_to_establishing() -> None:
    plan = plan_visuals(_script(_paragraph("p1")), _scenes(), _analyses(), _events())
    [clip] = plan.paragraph_clips
    assert (clip.scene_id, clip.reason) == ("scene_000001", "establishing fallback")


def test_unknown_refs_fall_back() -> None:
    plan = plan_visuals(_script(_paragraph("p1", "ghost")), _scenes(), _analyses(), _events())
    assert [c.scene_id for c in plan.paragraph_clips] == ["scene_000001"]


def test_all_paragraphs_covered() -> None:
    plan = plan_visuals(
        _script(_paragraph("p1", "scene_000001"), _paragraph("p2", "scene_000002")),
        _scenes(),
        _analyses(),
        _events(),
    )
    assert {c.paragraph_id for c in plan.paragraph_clips} == {"p1", "p2"}
