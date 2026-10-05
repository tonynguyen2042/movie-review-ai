"""T096 acceptance: publishing metadata derived from a review script."""

import pytest

from movie_review.domain import Claim, ReviewParagraph, ReviewScript, ReviewSection
from movie_review.publishing.metadata import (
    DESCRIPTION_MAX_CHARS,
    TITLE_MAX_CHARS,
    MetadataError,
    build_chapters,
    build_description,
    build_tags,
    build_title,
    generate_metadata,
    script_text,
)


def _paragraph(pid: str, text: str, target: int = 60) -> ReviewParagraph:
    return ReviewParagraph(
        id=pid,
        text=text,
        target_seconds=target,
        claims=[Claim(claim_id=f"{pid}-c1", type="PLOT_FACT", text=text)],
    )


def _script() -> ReviewScript:
    return ReviewScript(
        sections=[
            ReviewSection(
                id="s1",
                type="intro",
                paragraphs=[
                    _paragraph("p1", "The lighthouse keeper discovers the signal.", 30),
                    _paragraph("p2", "He suspects the captain lied about the storm.", 30),
                ],
            ),
            ReviewSection(
                id="s2",
                type="analysis",
                paragraphs=[
                    _paragraph("p3", "The keeper confronts the captain on the bridge.", 40),
                ],
            ),
        ]
    )


def test_script_text_concatenates_in_order() -> None:
    """Script text joins paragraphs in section then paragraph order."""
    text = script_text(_script())
    assert text.splitlines() == [
        "The lighthouse keeper discovers the signal.",
        "He suspects the captain lied about the storm.",
        "The keeper confronts the captain on the bridge.",
    ]


def test_build_title_uses_movie_title_and_hook() -> None:
    """Title combines the movie title with the first sentence as a hook."""
    title = build_title(_script(), "The Lighthouse")
    assert title.startswith("The Lighthouse Review |")
    assert "The lighthouse keeper discovers the signal" in title
    assert len(title) <= TITLE_MAX_CHARS


def test_build_title_truncates_to_limit() -> None:
    """An over-long movie title is truncated to the platform limit."""
    script = ReviewScript(
        sections=[
            ReviewSection(
                id="s1",
                type="intro",
                paragraphs=[_paragraph("p1", "Short hook sentence.", 10)],
            )
        ]
    )
    title = build_title(script, "M" * 300)
    assert len(title) <= TITLE_MAX_CHARS


def test_build_description_includes_summary_and_chapters() -> None:
    """Description contains a summary line and a chapter listing."""
    chapters = build_chapters(_script())
    description = build_description(_script(), "The Lighthouse", chapters)

    assert "The Lighthouse review." in description
    assert "Chapters:" in description
    assert "0:00 Intro" in description
    assert "1:00 Analysis" in description  # 30s + 30s = 60s -> 1:00
    assert len(description) <= DESCRIPTION_MAX_CHARS


def test_build_tags_ranks_by_frequency_and_drops_stopwords() -> None:
    """Tags are frequency-ranked, deduplicated, and free of stopwords."""
    script = ReviewScript(
        sections=[
            ReviewSection(
                id="s1",
                type="intro",
                paragraphs=[
                    _paragraph("p1", "lighthouse lighthouse keeper keeper captain", 10),
                    _paragraph("p2", "the keeper and the captain and the storm", 10),
                ],
            )
        ]
    )
    tags = build_tags(script, ["Movie Review"])

    assert tags[:2] == ["keeper", "captain"] or tags[:2] == ["captain", "keeper"]
    assert "lighthouse" in tags
    assert "the" not in tags
    assert "and" not in tags
    assert tags.count("keeper") == 1
    assert "Movie Review" in tags


def test_build_chapters_spaced_by_paragraph_targets() -> None:
    """Each chapter starts where the previous section's target time ends."""
    chapters = build_chapters(_script())
    assert [(c.index, c.title, c.start_seconds) for c in chapters] == [
        (1, "Intro", 0.0),
        (2, "Analysis", 60.0),
    ]


def test_generate_metadata_returns_all_fields() -> None:
    """Top-level generator fills title, description, tags, and chapters."""
    metadata = generate_metadata(_script(), "The Lighthouse", ["1960s", "Mystery"])
    assert metadata.title.startswith("The Lighthouse Review |")
    assert "Chapters:" in metadata.description
    assert "1960s" in metadata.tags
    assert "Mystery" in metadata.tags
    assert len(metadata.chapters) == 2


def test_generate_metadata_rejects_empty_script() -> None:
    """An empty script is a classified failure, not an empty result."""
    with pytest.raises(MetadataError):
        generate_metadata(ReviewScript.model_construct(sections=[]), "The Lighthouse")


def test_build_tags_folds_possessives_into_base_form() -> None:
    """Possessive forms collapse onto the base word (no duplicate tags)."""
    script = ReviewScript(
        sections=[
            ReviewSection(
                id="s1",
                type="intro",
                paragraphs=[
                    _paragraph("p1", "brother brother brother's captain's", 10),
                ],
            )
        ]
    )
    tags = build_tags(script)
    assert "brother" in tags
    assert "brother's" not in tags
    assert "captain" in tags
    assert "captain's" not in tags
    assert tags.count("brother") == 1


def test_build_description_preserves_line_structure() -> None:
    """Chapter markers stay on their own lines instead of collapsing."""
    script = ReviewScript(
        sections=[
            ReviewSection(
                id="s1",
                type="intro",
                paragraphs=[_paragraph("p1", "Opening line one.", 30)],
            ),
            ReviewSection(
                id="s2",
                type="analysis",
                paragraphs=[_paragraph("p2", "Opening line two.", 30)],
            ),
        ]
    )
    chapters = build_chapters(script)
    description = build_description(script, "Blackrock", chapters)
    lines = description.splitlines()
    assert lines[0] == "Blackrock review."
    assert "Chapters:" in lines
    assert lines[-3:] == ["Chapters:", "- 0:00 Intro", "- 0:30 Analysis"]


def test_metadata_is_deterministic() -> None:
    """The same script yields identical metadata (stable hashes/artifacts)."""
    first = generate_metadata(_script(), "The Lighthouse", ["Mystery"])
    second = generate_metadata(_script(), "The Lighthouse", ["Mystery"])
    assert first == second
