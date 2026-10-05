"""T043 acceptance: review writer prompt loads, renders, and constrains claims."""

from movie_review.config.prompts import load_prompt, render

VARS = {
    "outline": "hook then climax",
    "story": "events e1 e2",
    "style": "youtube",
    "target_words": "3000",
    "spoilers": "full",
}


def test_load_writer_prompt() -> None:
    prompt = load_prompt("script_writer")
    assert prompt.name == "script_writer"
    assert prompt.version == "v1"
    assert "SCRIPT RULES" in prompt.template
    assert len(prompt.sha256) == 64


def test_render_writer_prompt() -> None:
    text = render(load_prompt("script_writer", "v1"), **VARS)
    for value in VARS.values():
        assert value in text
    assert "$" not in text


def test_output_contract_present() -> None:
    text = render(load_prompt("script_writer"), **VARS)
    for key in ("sections", "paragraphs", "text", "target_seconds", "claims", "visual_intent"):
        assert key in text
    for claim_type in ("PLOT_FACT", "DIALOGUE_REFERENCE", "INTERPRETATION", "OPINION", "THEME"):
        assert claim_type in text
    assert "INSUFFICIENT_EVIDENCE" in text
