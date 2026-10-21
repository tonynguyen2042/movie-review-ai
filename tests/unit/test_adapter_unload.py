"""A model adapter must be released whether or not its work was cached.

T125 regression. In the transcript, story-arc, theme, twist and publishing
stages the `unload()` call sat inside the cache-miss branch. A cache hit
therefore constructed the adapter and dropped it without releasing it.

For the MLX backends `unload()` is what calls `mx.clear_cache()`, so the
weights stayed resident for the rest of the process -- directly against
`AGENTS.md`'s sequential-model-residency rule and the constitution's
"unload models between major stages where appropriate".

`vision/analysis.py` and `review/writer.py` already used the right shape, so
this is the five modules that were left behind.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from movie_review.asr.port import ASRPort
from movie_review.asr.transcript import run_transcript
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.reasoning.port import ReasoningPort
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


class _CountingAdapter(ASRPort):
    """A transcription adapter that records whether it was released."""

    def __init__(self) -> None:
        self.unloaded = 0
        self.calls = 0

    @property
    def model(self) -> str:
        return "counting"

    def transcribe(self, audio_path: str | Path, *, language: str | None = None) -> list[Any]:
        self.calls += 1
        return []

    def unload(self) -> None:
        self.unloaded += 1

    def available(self) -> bool:
        return True


def _ctx__adapter_unload(tmp_path: Path) -> tuple[StageContext, sqlite3.Connection]:
    movie = tmp_path / "movie.mp4"
    movie.write_bytes(b"\x00")
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file=str(movie)))
    manager.transition("job_1", JobStatus.INGESTING)
    manager.transition("job_1", JobStatus.MEDIA_READY)
    manager.transition("job_1", JobStatus.SCENES_READY)
    manager.transition("job_1", JobStatus.TRANSCRIPT_READY)
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
    )
    return ctx, conn


def _extract(source: Path, dest: Path, ffmpeg: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"\x00")
    return dest


def test_the_transcript_adapter_is_unloaded_on_a_cache_miss(tmp_path: Path) -> None:
    ctx, conn = _ctx__adapter_unload(tmp_path)
    movie = tmp_path / "movie.mp4"
    adapter = _CountingAdapter()
    try:
        run_transcript(
            str(movie),
            ctx,
            language="en",
            port=adapter,
            extract_fn=_extract,
        )
        assert adapter.calls == 1
        assert adapter.unloaded == 1
    finally:
        conn.close()


def test_the_transcript_adapter_is_unloaded_on_a_cache_hit(tmp_path: Path) -> None:
    """The regression: a cache hit skipped the model call and the release."""
    ctx, conn = _ctx__adapter_unload(tmp_path)
    movie = tmp_path / "movie.mp4"
    adapter = _CountingAdapter()
    try:
        run_transcript(
            str(movie),
            ctx,
            language="en",
            port=adapter,
            extract_fn=_extract,
        )
        # Second run: the cache answers, so the model is never called.
        second = _CountingAdapter()
        run_transcript(
            str(movie),
            ctx,
            language="en",
            port=second,
            extract_fn=_extract,
        )
        assert second.calls == 0, "the cache should have answered"
        assert second.unloaded == 1, "a cache hit must still release the adapter"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The three story stages
# ---------------------------------------------------------------------------


class _CountingReasoner(ReasoningPort):
    """A reasoning adapter that records whether it was released."""

    def __init__(self) -> None:
        self.unloaded = 0
        self.calls = 0

    @property
    def model(self) -> str:
        return "counting"

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        self.calls += 1
        return "[]"

    def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
        self.calls += 1
        return []

    def unload(self) -> None:
        self.unloaded += 1

    def available(self) -> bool:
        return True


def _story_stages__adapter_unload() -> list[tuple[str, Any]]:
    from movie_review.story.arcs import extract_story_arcs
    from movie_review.story.themes import extract_themes
    from movie_review.story.twists import extract_twists

    return [
        ("arcs", extract_story_arcs),
        ("themes", extract_themes),
        ("twists", extract_twists),
    ]


def test_the_story_stages_unload_on_a_cache_hit(tmp_path: Path) -> None:
    """Regression: the story stages skipped the release on a cache hit."""
    from movie_review.domain import Event, EventType

    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    events = [
        Event(
            id="event_00001",
            type=EventType.DISCOVERY,
            timestamp=10.0,
            description="Someone finds something.",
        )
    ]
    for name, stage in _story_stages__adapter_unload():
        reasoner = _CountingReasoner()
        kwargs = {
            "job_id": "job_1",
            "jobs_dir": tmp_path / "jobs",
            "conn": conn,
            "cache": CacheManager(tmp_path / "cache"),
            "spec": load_settings().models.reasoning,
            "reasoner": reasoner,
        }
        stage(events, "char_1: Someone", **kwargs)
        assert reasoner.calls == 1, f"{name} should have called the model"
        assert reasoner.unloaded == 1, f"{name} must release the adapter"

        # Second run: the cache answers, and the adapter must still be
        # released.
        second = _CountingReasoner()
        stage(events, "char_1: Someone", **{**kwargs, "reasoner": second})
        assert second.calls == 0, f"{name} should have hit the cache"
        assert second.unloaded == 1, f"{name} must release the adapter on a cache hit"
    conn.close()
