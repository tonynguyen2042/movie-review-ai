"""A cache key must bind every input that can change the answer.

T130 regression. The story stages hashed only the event lines, but the
rendered prompt also carried the character roster. Re-running with a
different roster therefore served the previous model's answer -- one
generated against the old roster.

The review writer was the milder form: it hashed the style's *name* but not
its tone, and not the outline's purpose or event ids, all of which are
rendered into the prompt.

`AGENTS.md` requires the cache identity to bind "every input that can change
an artifact". The whole rendered prompt is that input.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Event, EventType, Job, JobStatus
from movie_review.jobs.manager import JobManager
from movie_review.reasoning.port import ReasoningPort
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


class _RecordingReasoner(ReasoningPort):
    """A reasoning adapter that records the prompts it was asked."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    @property
    def model(self) -> str:
        return "recording"

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        self.prompts.append(prompt)
        return "[]"

    def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
        self.prompts.append(prompt)
        return []

    def unload(self) -> None:
        return None

    def available(self) -> bool:
        return True


class _WriterReasoner(_RecordingReasoner):
    """A reasoning adapter that answers with a valid script section."""

    def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
        self.prompts.append(prompt)
        return {
            "sections": [
                {
                    "id": "section_01",
                    "type": "hook",
                    "paragraphs": [
                        {
                            "id": "section_01p1",
                            "text": "Narration.",
                            "target_seconds": 12,
                            "claims": [],
                            "visual_intent": "establishing shot",
                        }
                    ],
                }
            ]
        }


def _events() -> list[Event]:
    return [
        Event(
            id="event_00001",
            type=EventType.DISCOVERY,
            timestamp=10.0,
            description="Someone finds something.",
        )
    ]


def _conn(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    return conn


def _story_stages() -> list[Any]:
    from movie_review.story.arcs import extract_story_arcs
    from movie_review.story.themes import extract_themes
    from movie_review.story.twists import extract_twists

    return [extract_story_arcs, extract_themes, extract_twists]


def test_a_different_roster_misses_the_cache(tmp_path: Path) -> None:
    """The roster is part of the prompt, so it has to be part of the key."""
    conn = _conn(tmp_path)
    cache = CacheManager(tmp_path / "cache")
    spec = load_settings().models.reasoning
    try:
        for stage in _story_stages():
            first = _RecordingReasoner()
            stage(
                _events(),
                "char_1: Someone",
                job_id="job_1",
                jobs_dir=tmp_path / "jobs",
                conn=conn,
                cache=cache,
                spec=spec,
                reasoner=first,
            )
            assert first.prompts, "the stage did not call the model"

            # A different roster, same events: the previous answer must not
            # be reused.
            second = _RecordingReasoner()
            stage(
                _events(),
                "char_1: Someone; char_2: Someone Else",
                job_id="job_1",
                jobs_dir=tmp_path / "jobs",
                conn=conn,
                cache=cache,
                spec=spec,
                reasoner=second,
            )
            assert second.prompts, "the cache answered for a different roster"
    finally:
        conn.close()


def test_the_same_roster_hits_the_cache(tmp_path: Path) -> None:
    """The fix must not turn every run into a miss."""
    from movie_review.story.arcs import extract_story_arcs

    conn = _conn(tmp_path)
    cache = CacheManager(tmp_path / "cache")
    spec = load_settings().models.reasoning
    try:
        first = _RecordingReasoner()
        extract_story_arcs(
            _events(),
            "char_1: Someone",
            job_id="job_1",
            jobs_dir=tmp_path / "jobs",
            conn=conn,
            cache=cache,
            spec=spec,
            reasoner=first,
        )
        assert first.prompts

        second = _RecordingReasoner()
        extract_story_arcs(
            _events(),
            "char_1: Someone",
            job_id="job_1",
            jobs_dir=tmp_path / "jobs",
            conn=conn,
            cache=cache,
            spec=spec,
            reasoner=second,
        )
        assert not second.prompts, "an unchanged input must still hit the cache"
    finally:
        conn.close()


def test_a_different_style_tone_misses_the_cache(tmp_path: Path) -> None:
    """The writer hashed the style's name but not its tone.

    The tone is rendered into the prompt, so a re-run with a different tone
    served the previous model's answer -- written in the old tone.
    """
    from movie_review.domain import OutlineSection, ReviewPlan
    from movie_review.pipeline.context import StageContext
    from movie_review.review.styles import load_style
    from movie_review.review.writer import write_script

    conn = _conn(tmp_path)
    manager = JobManager(conn)
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
        JobStatus.VISUAL_ANALYSIS_READY,
        JobStatus.CHARACTERS_READY,
        JobStatus.EVENTS_READY,
        JobStatus.STORY_READY,
    ):
        manager.transition("job_1", state)

    outline = ReviewPlan(
        sections=[
            OutlineSection(
                id="section_01",
                type="hook",
                target_seconds=40,
                event_ids=["event_00001"],
                purpose="hook",
            )
        ],
        total_seconds=40,
    )
    analysis: dict[str, Any] = {
        "events": [{"id": "event_00001", "timestamp": 5.0, "description": "Arrival."}],
        "characters": ["char_001"],
        "themes": [],
        "twists": [],
    }
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
    )
    spec = load_settings().models.reasoning

    first = _WriterReasoner()
    write_script(
        outline,
        analysis,
        load_style("youtube"),
        100,
        ctx,
        spec,
        reasoner=first,
    )
    assert first.prompts

    second = _WriterReasoner()
    write_script(
        outline,
        analysis,
        load_style("serious"),
        100,
        ctx,
        spec,
        reasoner=second,
    )
    assert second.prompts, "a different style must not reuse the cached section"

    third = _WriterReasoner()
    write_script(
        outline,
        analysis,
        load_style("youtube"),
        100,
        ctx,
        spec,
        reasoner=third,
    )
    assert not third.prompts, "an unchanged style must still hit the cache"
    conn.close()
