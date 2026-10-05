"""T040 acceptance: style profiles load and validate."""

from pathlib import Path

import pytest

from movie_review.review.styles import StyleError, list_styles, load_style


def test_lists_four_styles() -> None:
    assert list_styles() == ["documentary", "funny", "serious", "youtube"]


def test_youtube_matches_spec() -> None:
    style = load_style("youtube")
    assert style.tone["conversational"] == pytest.approx(0.8)
    assert style.content["ending_explanation"] == pytest.approx(1.0)
    assert style.hook["max_seconds"] == 45
    assert style.spoilers == "full"
    assert (style.target_duration_seconds, style.target_wpm) == (1200, 150)


def test_all_styles_valid() -> None:
    for name in list_styles():
        style = load_style(name)
        assert style.name == name
        assert style.target_duration_seconds > 0
        assert style.target_wpm > 0


def test_unknown_style_rejected() -> None:
    with pytest.raises(StyleError, match="Unknown style"):
        load_style("noir")


def test_bad_files_rejected(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text("tone: [unclosed", encoding="utf-8")
    with pytest.raises(StyleError, match="Invalid style file"):
        load_style("broken", tmp_path)
    (tmp_path / "oob.yaml").write_text(
        "name: oob\ntone:\n  conversational: 1.5\n", encoding="utf-8"
    )
    with pytest.raises(StyleError, match="Invalid style"):
        load_style("oob", tmp_path)
    (tmp_path / "flat.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(StyleError, match="mapping"):
        load_style("flat", tmp_path)
