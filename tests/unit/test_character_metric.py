"""T066 acceptance: character consistency scoring."""

from movie_review.domain import (
    Character,
    CharacterMention,
    Event,
    EventType,
)
from movie_review.quality.characters import character_consistency


def _character__character_metric(character_id: str = "char_001") -> Character:
    return Character(id=character_id, name="John", first_seen=0.0, last_seen=90.0)


def _mention(text: str, character_id: str | None) -> CharacterMention:
    return CharacterMention(
        mention=text, source_segment_id="seg_1", timestamp=1.0, character_id=character_id
    )


def _death() -> list[Event]:
    return [
        Event(
            id="e1",
            type=EventType.DEATH,
            timestamp=50.0,
            characters=["char_001"],
            description="John dies.",
        ),
        Event(
            id="e2",
            type=EventType.ACTION,
            timestamp=60.0,
            characters=["char_001"],
            description="John acts.",
        ),
    ]


def test_clean_scores_100() -> None:
    metric = character_consistency(
        [_character__character_metric()],
        [_mention("John", "char_001")],
        [("SPEAKER_00", "char_001", 0.8)],
        [],
        [],
    )
    assert metric.name == "character_consistency"
    assert metric.score == 100.0


def test_dangling_penalized() -> None:
    metric = character_consistency(
        [_character__character_metric()],
        [_mention("Zorg", "char_999")],
        [("SPEAKER_01", "char_998", 0.5)],
        [],
        [],
    )
    assert metric.score == 0.0
    assert "char_999" in metric.detail


def test_death_issue_penalized() -> None:
    metric = character_consistency(
        [_character__character_metric()], [_mention("John", "char_001")], [], _death(), []
    )
    assert metric.score == 50.0


def test_vacuous() -> None:
    assert character_consistency([], [], [], [], []).score == 100.0
