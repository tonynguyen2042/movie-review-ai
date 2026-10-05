"""Speaker-to-character linking via scene co-occurrence (T029, FR-008).

Deterministic baseline: a speaker active in scenes listing a character
accumulates evidence; exclusive scenes (one listed character, one active
speaker) weigh more. Ambiguous speakers stay unlinked rather than guessed.
Face recognition, embeddings, and LLM reasoning arrive with later adapters.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field

from movie_review.domain import DiarizedSegment, Scene, SceneAnalysis
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

UNIQUENESS_BONUS = 2
MIN_SCORE = 1
MIN_MARGIN = 1


@dataclass(frozen=True)
class SpeakerLink:
    """One speaker's resolved character (None when ambiguous)."""

    speaker: str
    character_id: str | None
    confidence: float
    reasons: list[str] = field(default_factory=list)


def _overlaps(start: float, end: float, span: tuple[float, float]) -> bool:
    return start < span[1] and end > span[0]


def link_speakers(
    turns: list[DiarizedSegment],
    scenes: list[Scene],
    analyses: dict[str, SceneAnalysis],
    character_ids: dict[str, str],
    uniqueness_bonus: int = UNIQUENESS_BONUS,
    min_score: int = MIN_SCORE,
    min_margin: int = MIN_MARGIN,
) -> list[SpeakerLink]:
    """Map speaker labels to character IDs; abstain on ambiguity.

    Args:
        turns: diarized speaker spans.
        scenes: scene timeline.
        analyses: VLM analyses keyed by scene ID.
        character_ids: character name (lowercased) → character ID.
    """
    speakers = sorted({turn.speaker for turn in turns})
    scores: dict[str, dict[str, int]] = {speaker: {} for speaker in speakers}
    evidence: dict[str, dict[str, list[str]]] = {speaker: {} for speaker in speakers}

    for scene in scenes:
        analysis = analyses.get(scene.scene_id)
        if analysis is None:
            continue
        span = (scene.start, scene.end)
        active = sorted({turn.speaker for turn in turns if _overlaps(turn.start, turn.end, span)})
        listed = [name for name in analysis.characters if name.lower() in character_ids]
        for speaker in active:
            for name in listed:
                character_id = character_ids[name.lower()]
                scores[speaker][character_id] = scores[speaker].get(character_id, 0) + 1
                evidence[speaker].setdefault(character_id, []).append(
                    f"co-occurs in {scene.scene_id}"
                )
        if len(active) == 1 and len(listed) == 1:
            character_id = character_ids[listed[0].lower()]
            scores[active[0]][character_id] += uniqueness_bonus
            evidence[active[0]][character_id].append(f"alone with {listed[0]} in {scene.scene_id}")

    links = []
    for speaker in speakers:
        ranked = sorted(scores[speaker].items(), key=lambda item: (-item[1], item[0]))
        if not ranked or ranked[0][1] < min_score:
            links.append(SpeakerLink(speaker=speaker, character_id=None, confidence=0.0))
            continue
        top_id, top_score = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        if top_score - runner_up < min_margin:
            links.append(SpeakerLink(speaker=speaker, character_id=None, confidence=0.0))
            continue
        links.append(
            SpeakerLink(
                speaker=speaker,
                character_id=top_id,
                confidence=min(0.5 + 0.1 * top_score, 0.95),
                reasons=evidence[speaker][top_id],
            )
        )
    with ulog.logging_context(stage="characters"):
        ulog.log_event(
            _logger,
            event="linking.completed",
            status="ok",
            linked=sum(1 for link in links if link.character_id),
        )
    return links


def save_links(conn: sqlite3.Connection, job_id: str, links: list[SpeakerLink]) -> None:
    """Persist speaker links through the T029 repository."""
    for link in links:
        repo.save_speaker_link(conn, job_id, link.speaker, link.character_id, link.confidence)
