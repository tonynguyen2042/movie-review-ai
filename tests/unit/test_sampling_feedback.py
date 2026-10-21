"""The frame budget must be feedback-driven, not a pure function of length.

T146. `media/feedback.py::apply_feedback` was complete and tested, and the
vision stage never called it. README section 12 asks for the sampler to
increase the frame budget for a scene that matters — high importance,
observed actions, an unseen character — and to reduce it for a scene with
nothing in it. The budget was a pure function of the scene's duration.
"""

from __future__ import annotations

from pathlib import Path

from movie_review.domain import Scene, SceneAnalysis
from movie_review.media.feedback import (
    FeedbackConfig,
    decide_feedback,
)


def _scene(scene_id: str = "scene_000001", duration: float = 20.0) -> Scene:
    return Scene(
        scene_id=scene_id,
        start=0.0,
        end=duration,
        duration=duration,
    )


def _analysis(
    importance: float = 0.5,
    actions: list[str] | None = None,
    characters: list[str] | None = None,
) -> SceneAnalysis:
    return SceneAnalysis(
        scene_id="scene_000001",
        location="here",
        characters=characters or [],
        actions=actions or [],
        objects=[],
        emotions=[],
        visual_events=[],
        importance=importance,
    )


def test_an_important_scene_gets_more_frames() -> None:
    """The importance boost was never applied."""
    decision = decide_feedback(
        _scene(),
        _analysis(importance=0.95),
        "some dialogue",
        frozenset(),
        base_count=6,
    )
    assert decision.adjusted_count > 6
    assert decision.boosted is True
    assert any("importance" in reason for reason in decision.reasons)


def test_an_observed_action_gets_more_frames() -> None:
    decision = decide_feedback(
        _scene(),
        _analysis(actions=["a door opens"]),
        "some dialogue",
        frozenset(),
        base_count=6,
    )
    assert decision.adjusted_count > 6
    assert any("actions" in reason for reason in decision.reasons)


def test_a_new_character_gets_more_frames() -> None:
    decision = decide_feedback(
        _scene(),
        _analysis(characters=["Sarah"]),
        "some dialogue",
        frozenset(),
        base_count=6,
    )
    assert decision.adjusted_count > 6
    assert any("new characters" in reason for reason in decision.reasons)


def test_a_low_information_scene_gets_fewer_frames() -> None:
    """A static scene with nothing in it does not need twelve frames."""
    decision = decide_feedback(
        _scene(),
        _analysis(importance=0.1),
        "",
        frozenset(),
        base_count=8,
    )
    assert decision.adjusted_count < 8
    assert any("low information" in reason for reason in decision.reasons)


def test_the_budget_stays_inside_its_bounds() -> None:
    """A very important scene must not ask for a thousand frames."""
    decision = decide_feedback(
        _scene(),
        _analysis(importance=1.0, actions=["a", "b", "c"], characters=["A", "B", "C"]),
        "dialogue",
        frozenset(),
        base_count=20,
        config=FeedbackConfig(),
    )
    assert decision.adjusted_count <= 24


def test_the_vision_stage_calls_the_feedback() -> None:
    """The feedback module was written and nothing called it."""
    from movie_review.pipeline import orchestrator

    source = Path(orchestrator.__file__).read_text(encoding="utf-8")
    assert "apply_feedback" in source
    assert "decide_feedback" not in source, "the stage must use the module's decision"
