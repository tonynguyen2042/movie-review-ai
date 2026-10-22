"""Attribute the transcript's lines to speakers, and the speakers to characters.

T144. The diarization adapter and the speaker-linking module were both
complete and tested, and no stage called either of them. The speakers
table was always empty, the transcript carried no attribution, and
``pipeline.diarization`` in the configuration was a flag that did nothing.

README sections 14 and 17 ask for this: the transcript's lines belong to
``SPEAKER_00``, ``SPEAKER_01`` and so on, and those labels are resolved to
characters later, by evidence rather than by face recognition.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from movie_review.characters.linking import link_speakers, save_links
from movie_review.diarization.initial import EnergyDiarizer
from movie_review.diarization.port import DiarizationPort
from movie_review.domain import DiarizedSegment, JobStatus, TranscriptSegment
from movie_review.jobs.failure import job_failure_message
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "diarization"
STAGE_VERSION = "v1"


class DiarizationStageError(Exception):
    """The diarization stage failed in a classified way."""


@dataclass
class DiarizationStageResult:
    """The outcome of one diarization run."""

    turns: list[DiarizedSegment]
    linked: int
    attributed: int
    duration_ms: int


def _attribute(segments: list[TranscriptSegment], turns: list[DiarizedSegment]) -> dict[str, str]:
    """The speaker of each transcript segment.

    A segment belongs to the diarized span it overlaps the most. A segment
    that overlaps no span keeps no speaker rather than being given one by
    accident.
    """
    speakers: dict[str, str] = {}
    for segment in segments:
        best: str | None = None
        best_overlap = 0.0
        for turn in turns:
            overlap = min(segment.end, turn.end) - max(segment.start, turn.start)
            if overlap > best_overlap:
                best_overlap = overlap
                best = turn.speaker
        if best is not None:
            speakers[segment.segment_id] = best
    return speakers


def run_diarization(
    audio_path: Path,
    ctx: StageContext,
    port: DiarizationPort | None = None,
) -> DiarizationStageResult:
    """Diarize the dialogue audio and link the speakers to the characters."""
    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise DiarizationStageError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise DiarizationStageError(job_failure_message(job))

    if not audio_path.is_file():
        raise DiarizationStageError(f"No dialogue audio at {audio_path}")

    active = port or EnergyDiarizer()
    try:
        turns = active.diarize(audio_path)
    except Exception as exc:
        raise DiarizationStageError(f"Cannot diarize {audio_path}: {exc}") from exc

    # Each line is attributed to the speaker it overlaps most.
    segments = repo.list_transcript_segments(ctx.conn, ctx.job_id)
    speakers = _attribute(segments, turns)
    if speakers:
        attributed = [
            segment.model_copy(update={"speaker": speakers[segment.segment_id]})
            if segment.segment_id in speakers
            else segment
            for segment in segments
        ]
        repo.save_transcript_segments(ctx.conn, ctx.job_id, attributed)

    # The speakers are resolved to characters by co-occurrence. A speaker
    # that stays ambiguous keeps no character rather than being guessed.
    scenes = repo.list_scenes(ctx.conn, ctx.job_id)
    analyses = {
        analysis.scene_id: analysis for analysis in repo.list_scene_analyses(ctx.conn, ctx.job_id)
    }
    characters = repo.list_characters(ctx.conn, ctx.job_id)
    character_ids = {character.name.lower(): character.id for character in characters}
    links = link_speakers(turns, scenes, analyses, character_ids)
    save_links(ctx.conn, ctx.job_id, links)

    linked = sum(1 for link in links if link.character_id)
    duration_ms = int((time.perf_counter() - started) * 1000)
    with ulog.logging_context(job_id=ctx.job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="stage.completed",
            status="ok",
            duration_ms=duration_ms,
            turns=len(turns),
            speakers=len({turn.speaker for turn in turns}),
            linked=linked,
            attributed=len(speakers),
        )

    return DiarizationStageResult(
        turns=turns,
        linked=linked,
        attributed=len(speakers),
        duration_ms=duration_ms,
    )
