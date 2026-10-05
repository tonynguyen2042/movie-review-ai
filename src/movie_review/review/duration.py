"""Duration controller: fit scripts to narration targets (T050, spec section 93).

Word math follows ``target_words = duration_seconds * wpm / 60``. Over-long
scripts compress by dropping the lowest-value paragraphs (fewest claims,
never a section's last paragraph); short scripts report ``expand-required``
instead of padding with repetitive summary — expansion needs the writer.
"""

from __future__ import annotations

from dataclasses import dataclass

from movie_review.domain import ReviewScript

TOLERANCE_RATIO = 0.02


def count_words(text: str) -> int:
    """Whitespace-separated word count."""
    return len(text.split())


def script_words(script: ReviewScript) -> int:
    """Total narration words across all paragraphs."""
    return sum(
        count_words(paragraph.text)
        for section in script.sections
        for paragraph in section.paragraphs
    )


def target_words(duration_seconds: float, wpm: int) -> int:
    """Target narration words for a duration at a speech rate."""
    if duration_seconds <= 0:
        raise ValueError(f"Duration must be positive: {duration_seconds}")
    if wpm <= 0:
        raise ValueError(f"WPM must be positive: {wpm}")
    return round(duration_seconds * wpm / 60)


@dataclass(frozen=True)
class FitResult:
    """Fitted script plus the action taken."""

    script: ReviewScript
    action: str
    word_count: int
    target: int
    removed: list[str]


def fit_script(
    script: ReviewScript, target: int, tolerance_ratio: float = TOLERANCE_RATIO
) -> FitResult:
    """Fit a script copy to ``target`` words (never pads with filler)."""
    if target <= 0:
        raise ValueError(f"Target must be positive: {target}")
    words = script_words(script)
    tolerance = max(1, round(target * tolerance_ratio))
    if abs(words - target) <= tolerance:
        return FitResult(script=script, action="ok", word_count=words, target=target, removed=[])
    if words < target:
        return FitResult(
            script=script,
            action="expand-required",
            word_count=words,
            target=target,
            removed=[],
        )

    droppable = sorted(
        (len(paragraph.claims), -paragraph.target_seconds, section.id, paragraph.id)
        for section in script.sections
        if len(section.paragraphs) > 1
        for paragraph in section.paragraphs
    )
    remaining = {section.id: len(section.paragraphs) for section in script.sections}
    dropped: set[str] = set()
    for _, _, section_id, paragraph_id in droppable:
        if words <= target + tolerance:
            break
        if remaining[section_id] <= 1:
            continue
        dropped.add(paragraph_id)
        remaining[section_id] -= 1
        words -= _paragraph_words(script, paragraph_id)
    kept_sections = [
        section.model_copy(
            update={"paragraphs": [p for p in section.paragraphs if p.id not in dropped]}
        )
        for section in script.sections
    ]
    removed = [
        paragraph.id
        for section in script.sections
        for paragraph in section.paragraphs
        if paragraph.id in dropped
    ]
    fitted = script.model_copy(update={"sections": kept_sections})
    return FitResult(
        script=fitted,
        action="compressed",
        word_count=script_words(fitted),
        target=target,
        removed=removed,
    )


def _paragraph_words(script: ReviewScript, paragraph_id: str) -> int:
    for section in script.sections:
        for paragraph in section.paragraphs:
            if paragraph.id == paragraph_id:
                return count_words(paragraph.text)
    return 0
