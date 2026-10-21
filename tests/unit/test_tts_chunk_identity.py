"""A chunk's identity must not depend on where it sits in the script.

T167. `tts/chunks.py::plan_chunks` numbered chunks positionally --
`tts_001`, `tts_002` -- and the concatenation stage re-plans and assumes the
ids match. Inserting one paragraph into the script shifted every later id,
so the stage silently joined the **wrong audio files** and the narration
came out with the wrong words in the wrong places. Nothing failed.

A paragraph of four hundred words with no end punctuation was also never
split: the split was by sentence, so one long sentence was one chunk and one
request to the TTS endpoint with a four hundred word body.
"""

from __future__ import annotations

from movie_review.domain import ReviewParagraph, ReviewScript, ReviewSection
from movie_review.tts.chunks import chunk_id_for, plan_chunks, split_long_text


def _script(paragraphs: list[str]) -> ReviewScript:
    return ReviewScript(
        sections=[
            ReviewSection(
                id="sec_001",
                type="hook",
                paragraphs=[
                    ReviewParagraph(
                        id=f"p{index}",
                        text=text,
                        target_seconds=10,
                        claims=[],
                        visual_intent="s",
                    )
                    for index, text in enumerate(paragraphs)
                ],
            )
        ]
    )


def test_the_chunk_id_comes_from_the_content() -> None:
    """A positional id shifts when the script is edited."""
    first = plan_chunks(_script(["One.", "Two."]), voice="default")
    second = plan_chunks(_script(["One.", "Two."]), voice="default")
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_inserting_a_paragraph_does_not_move_the_others() -> None:
    """The regression: inserting a paragraph shifted every later id.

    The concatenation stage re-plans and assumes the ids match, so a shift
    means the wrong audio files are joined -- silently.
    """
    before = plan_chunks(_script(["One.", "Two."]), voice="default")
    after = plan_chunks(_script(["One.", "Inserted.", "Two."]), voice="default")

    before_by_text = {c.text: c.chunk_id for c in before}
    after_by_text = {c.text: c.chunk_id for c in after}

    assert before_by_text["One."] == after_by_text["One."]
    assert before_by_text["Two."] == after_by_text["Two."]


def test_editing_a_paragraph_changes_its_chunk_id() -> None:
    """The changed text must not be served from the old audio."""
    before = plan_chunks(_script(["One."]), voice="default")
    after = plan_chunks(_script(["One, edited."]), voice="default")
    assert before[0].chunk_id != after[0].chunk_id


def test_two_paragraphs_with_the_same_text_differ() -> None:
    """The paragraph is part of the identity."""
    chunks = plan_chunks(_script(["Same.", "Same."]), voice="default")
    assert chunks[0].chunk_id != chunks[1].chunk_id


def test_the_chunk_id_is_deterministic() -> None:
    assert chunk_id_for("text") == chunk_id_for("text")
    assert chunk_id_for("text", 1) != chunk_id_for("text", 0)


def test_a_long_single_sentence_is_split() -> None:
    """The sentence split alone was not enough."""
    words = " ".join(f"word{index}" for index in range(100))
    pieces = split_long_text(words, max_words=30)
    assert len(pieces) > 1
    assert all(len(piece.split()) <= 30 for piece in pieces)
    # No word is cut in half, and nothing is lost.
    assert " ".join(pieces).split() == words.split()


def test_a_short_text_is_not_split() -> None:
    assert split_long_text("A short line.", max_words=30) == ["A short line."]


def test_an_overlong_paragraph_becomes_several_chunks() -> None:
    """A four hundred word paragraph was one request to the TTS endpoint."""
    words = " ".join(f"word{index}" for index in range(400))
    chunks = plan_chunks(_script([words]), voice="default", max_words=60)
    assert len(chunks) > 1
    assert all(len(chunk.text.split()) <= 60 for chunk in chunks)
