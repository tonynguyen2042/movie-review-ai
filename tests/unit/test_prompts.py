"""T024 acceptance: versioned prompts load, render, and fail loudly."""

from pathlib import Path

import pytest

from movie_review.config.prompts import (
    PromptError,
    list_versions,
    load_prompt,
    render,
)

VARS = {
    "scene_id": "scene_000001",
    "frame_count": "6",
    "metadata": "25.0s at 25fps",
    "dialogue": "Hello world",
    "previous_summary": "none",
}


def test_load_latest() -> None:
    prompt = load_prompt("scene_analysis")
    assert prompt.name == "scene_analysis"
    assert prompt.version == "v1"
    assert "ROLE" in prompt.template
    assert "confidence" in prompt.template
    assert len(prompt.sha256) == 64


def test_render_substitutes_all() -> None:
    prompt = load_prompt("scene_analysis", "v1")
    text = render(prompt, **VARS)
    for value in VARS.values():
        assert value in text
    assert "$" not in text


def test_render_missing_variable_rejected() -> None:
    prompt = load_prompt("scene_analysis")
    with pytest.raises(PromptError, match="Missing prompt variable"):
        render(prompt, scene_id="s")


def test_unknown_prompt_rejected() -> None:
    with pytest.raises(PromptError, match="Unknown prompt"):
        load_prompt("nope")


def test_unknown_version_rejected() -> None:
    with pytest.raises(PromptError, match="Unknown prompt version"):
        load_prompt("scene_analysis", "v99")


def test_unsafe_version_rejected() -> None:
    with pytest.raises(PromptError, match="Unsafe prompt version"):
        load_prompt("scene_analysis", "../x")


def test_list_versions(tmp_path: Path) -> None:
    body = "---\nname: demo\nversion: v2\n---\nhello $who\n"
    (tmp_path / "demo_v2.md").write_text(body, encoding="utf-8")
    (tmp_path / "demo_v1.md").write_text(body.replace("v2", "v1"), encoding="utf-8")
    assert list_versions("demo", tmp_path) == ["v1", "v2"]
    assert load_prompt("demo", base=tmp_path).version == "v2"
    assert render(load_prompt("demo", "v1", tmp_path), who="you") == "hello you\n"


def test_bad_frontmatter_rejected(tmp_path: Path) -> None:
    (tmp_path / "bad_v1.md").write_text("no frontmatter here", encoding="utf-8")
    with pytest.raises(PromptError, match="frontmatter"):
        load_prompt("bad", base=tmp_path)
    (tmp_path / "mismatch_v1.md").write_text(
        "---\nname: other\nversion: v1\n---\nbody\n", encoding="utf-8"
    )
    with pytest.raises(PromptError, match="mismatched name"):
        load_prompt("mismatch", base=tmp_path)
