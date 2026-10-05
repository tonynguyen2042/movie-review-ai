"""Character consistency metric (T066, spec gate >= 95).

Share of character references that resolve plus absence of post-death
activity, as a 0-100 score. Vacuously 100 when nothing references anyone.
"""

from __future__ import annotations

from movie_review.domain import Character, CharacterMention, Event, QualityMetric, Scene
from movie_review.review.continuity import check_continuity


def character_consistency(
    characters: list[Character],
    mentions: list[CharacterMention],
    speaker_links: list[tuple[str, str | None, float]],
    events: list[Event],
    scenes: list[Scene],
) -> QualityMetric:
    """Score link resolution and death consistency."""
    known = {character.id for character in characters}
    dangling = [
        mention.character_id
        for mention in mentions
        if mention.character_id is not None and mention.character_id not in known
    ]
    dangling.extend(
        character_id
        for _, character_id, _ in speaker_links
        if character_id is not None and character_id not in known
    )
    death_issues = [
        issue
        for issue in check_continuity(events, scenes)
        if issue.kind == "character-active-after-death"
    ]
    refs = sum(1 for mention in mentions if mention.character_id is not None)
    refs += sum(1 for _, character_id, _ in speaker_links if character_id is not None)
    total = refs + len(death_issues)
    if total == 0:
        return QualityMetric(
            name="character_consistency", score=100.0, detail="no character references"
        )
    violations = len(dangling) + len(death_issues)
    score = (total - violations) / total * 100.0
    detail = f"{total - violations}/{total} references consistent"
    problems = [f"dangling: {sorted(set(dangling))}"] if dangling else []
    problems += [issue.detail for issue in death_issues]
    if problems:
        detail += "; " + "; ".join(problems)
    return QualityMetric(name="character_consistency", score=score, detail=detail)
