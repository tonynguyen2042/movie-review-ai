"""T050 acceptance: word math and compression without padding."""

import pytest

from movie_review.domain import Claim, ClaimType, ReviewParagraph, ReviewScript, ReviewSection
from movie_review.review.duration import (
    count_words,
    fit_script,
    script_words,
    target_words,
)


def _paragraph(paragraph_id: str, words: int, claims: int = 1) -> ReviewParagraph:
    return ReviewParagraph(
        id=paragraph_id,
        text=" ".join(f"word{n}" for n in range(words)),
        target_seconds=12,
        claims=[
            Claim(
                claim_id=f"{paragraph_id}c{i}",
                text="Fact here.",
                type=ClaimType.PLOT_FACT,
                evidence=["e1"],
            )
            for i in range(claims)
        ],
        visual_intent="shot",
    )


def _script() -> ReviewScript:
    return ReviewScript(
        sections=[
            ReviewSection(
                id="sec_01",
                type="hook",
                paragraphs=[_paragraph("p1", 100, 2), _paragraph("p2", 100, 0)],
            ),
            ReviewSection(id="sec_02", type="climax", paragraphs=[_paragraph("p3", 100, 1)]),
        ]
    )


def test_word_math() -> None:
    assert count_words("  hello   world ") == 2
    assert target_words(1200, 150) == 3000
    with pytest.raises(ValueError):
        target_words(0, 150)
    with pytest.raises(ValueError):
        target_words(1200, 0)


def test_fit_ok_within_tolerance() -> None:
    result = fit_script(_script(), 300)
    assert result.action == "ok"
    assert result.word_count == 300
    assert result.removed == []


def test_compress_drops_lowest_value() -> None:
    result = fit_script(_script(), 150)
    assert result.action == "compressed"
    assert result.removed == ["p2"]
    assert result.word_count == 200
    remaining = [p.id for s in result.script.sections for p in s.paragraphs]
    assert remaining == ["p1", "p3"]


def test_compress_protects_last_paragraph() -> None:
    script = _script()
    result = fit_script(script, 50)
    ids = [p.id for s in result.script.sections for p in s.paragraphs]
    assert "p1" in ids and "p3" in ids
    assert result.action == "compressed"


def test_short_requests_expansion() -> None:
    result = fit_script(_script(), 1000)
    assert result.action == "expand-required"
    assert result.word_count == 300
    assert result.removed == []


def test_bad_target_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        fit_script(_script(), 0)


def test_script_words() -> None:
    assert script_words(_script()) == 300
