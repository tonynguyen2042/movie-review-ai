"""A prompt must not carry the same information a thousand times.

T140 regression. Three separate duplications.

The story stages sent the whole character roster in every per-scene prompt:
532 discovered candidates made an 11.9 KB block, so a thousand scene
prompts carried about three million tokens of the same names.

The review writer built one story brief -- 83 554 characters, about 21 000
tokens -- and interpolated it into all eight section prompts: 167 000
duplicated tokens, and a single prompt that size exceeds the context of a
14B model.

The events stage hashed the whole prior-event list into its cache key
although the prompt shows the last twenty of them, so the key grew with the
length of the film and a change to an early event invalidated every later
scene's entry.
"""

from __future__ import annotations

from typing import Any

from movie_review.domain import Character, SceneAnalysis
from movie_review.review.writer import _story_brief
from movie_review.story.events import _scene_character_lines


def _characters(count: int) -> list[Character]:
    return [
        Character(
            id=f"char_{index:03d}",
            name=f"Character {index}",
            aliases=[],
            first_seen=0.0,
            last_seen=1.0,
        )
        for index in range(count)
    ]


def test_the_scene_roster_is_bounded() -> None:
    """A scene must not be told about five hundred characters."""
    characters = _characters(500)
    analysis = SceneAnalysis(
        scene_id="scene_000001",
        location="here",
        characters=["Character 3"],
        actions=[],
        objects=[],
        emotions=[],
        visual_events=[],
        importance=0.5,
    )
    lines = _scene_character_lines(characters, analysis)
    assert len(lines.splitlines()) <= 13, f"the roster was {len(lines)} lines"
    assert "char_003: Character 3" in lines


def test_the_characters_the_scene_names_come_first() -> None:
    """The people in the scene matter more than the people who are not."""
    characters = _characters(40)
    analysis = SceneAnalysis(
        scene_id="scene_000001",
        location="here",
        characters=["Character 30"],
        actions=[],
        objects=[],
        emotions=[],
        visual_events=[],
        importance=0.5,
    )
    lines = _scene_character_lines(characters, analysis)
    assert lines.splitlines()[0] == "char_030: Character 30"


def test_the_story_brief_is_bounded() -> None:
    """A brief of 21 000 tokens exceeds a 14B model's context."""
    analysis: dict[str, Any] = {
        "events": [
            {
                "id": f"event_{index:05d}",
                "timestamp": float(index),
                "description": "Something happens, at some length, in the story.",
            }
            for index in range(400)
        ],
        "characters": [{"name": f"Character {index}"} for index in range(500)],
        "themes": [],
        "twists": [],
    }
    brief = _story_brief(analysis)
    assert len(brief) < 20000, f"the brief was {len(brief)} characters"
    assert brief.count("Something happens") <= 24


def test_the_brief_can_be_narrowed_to_a_sections_events() -> None:
    """A section prompt carries the events that section is about."""
    analysis: dict[str, Any] = {
        "events": [
            {
                "id": f"event_{index:05d}",
                "timestamp": float(index),
                "description": f"Event number {index} happens.",
            }
            for index in range(100)
        ],
        "characters": [],
        "themes": [],
        "twists": [],
    }
    brief = _story_brief(analysis, ["event_00042"])
    assert "Event number 42 happens." in brief
    assert "Event number 7 happens." not in brief


def test_the_brief_falls_back_to_the_whole_story() -> None:
    """A section that cites no event still gets a story."""
    analysis: dict[str, Any] = {
        "events": [{"id": "event_00001", "timestamp": 1.0, "description": "It happened."}],
        "characters": [],
        "themes": [],
        "twists": [],
    }
    brief = _story_brief(analysis, ["event_does_not_exist"])
    assert "It happened." in brief


def test_the_characters_are_formatted_compactly() -> None:
    """The raw repr of the parsed objects was dict syntax in every prompt."""
    analysis: dict[str, Any] = {
        "events": [],
        "characters": [{"id": "char_001", "name": "Sarah", "aliases": []}],
        "themes": [],
        "twists": [],
    }
    brief = _story_brief(analysis)
    assert "Sarah" in brief
    assert "'aliases'" not in brief
