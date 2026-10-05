"""T032 acceptance: event extraction prompt loads, renders, matches Event."""

from movie_review.config.prompts import load_prompt, render
from movie_review.domain import Event

VARS = {
    "scenes": "scene_000001 (0-60s)",
    "dialogue": "Where were you?",
    "characters": "char_001 John",
    "prior_events": "none",
}


def test_load_event_prompt() -> None:
    prompt = load_prompt("event_extraction")
    assert prompt.name == "event_extraction"
    assert prompt.version == "v1"
    assert "FAILURE BEHAVIOR" in prompt.template
    assert len(prompt.sha256) == 64


def test_render_event_prompt() -> None:
    text = render(load_prompt("event_extraction", "v1"), **VARS)
    for value in VARS.values():
        assert value in text
    assert "$" not in text


def test_output_matches_event_schema() -> None:
    entry = {
        "type": "DISCOVERY",
        "timestamp": 1523.8,
        "characters": ["char_001"],
        "location": "loc_04",
        "description": "John discovers the hidden photograph.",
        "importance": 0.91,
        "evidence": ["scene_000123"],
    }
    event = Event(id="event_00031", **entry)  # type: ignore[arg-type]
    assert event.type.value == "DISCOVERY"


def test_prompt_lists_all_event_types() -> None:
    text = render(load_prompt("event_extraction"), **VARS)
    for event_type in ("BETRAYAL", "FLASH_FORWARD", "CLIMAX", "RESOLUTION", "OTHER"):
        assert event_type in text
