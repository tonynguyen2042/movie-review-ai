"""T187 acceptance: events concurrency is configuration, not a constant.

The events stage -- one reasoning call per scene -- kept its in-flight
budget hard-coded to 4, so an operator on a remote endpoint that serves
requests in flight could not use that parallelism.
``pipeline.event_extraction.concurrency`` now carries the value: the stage
honours it, and the orchestrator's events stage passes the configured
number through to ``run_event_extraction``.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings, read_yaml, repo_root
from movie_review.domain import Event, EventType, Job, JobStatus, Scene, SceneAnalysis
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.orchestrator import PipelineContext, _get_stage_function
from movie_review.reasoning.port import ReasoningPort
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.story.events import (
    DEFAULT_CONCURRENCY,
    EventExtractionError,
    EventsResult,
    run_event_extraction,
)


class _InFlightPort__event_extraction_concurrency(ReasoningPort):
    """A port that measures how many of its calls overlap."""

    def __init__(self, hold_seconds: float = 0.05) -> None:
        self._hold = hold_seconds
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0

    @property
    def model(self) -> str:
        return "rec-reasoning"

    def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            time.sleep(self._hold)
            return [{"type": "ACTION", "timestamp": 1.0, "description": "something happens"}]
        finally:
            with self._lock:
                self._in_flight -= 1

    def complete(self, prompt: str, *, temperature: float | None = None) -> str:
        raise AssertionError("the stage must use complete_json")

    def unload(self) -> None:
        return None


def _analysis__event_extraction_concurrency(scene_id: str) -> SceneAnalysis:
    return SceneAnalysis(
        scene_id=scene_id,
        location="a room",
        characters=[],
        actions=["someone moves"],
        objects=[],
        emotions=[],
        visual_events=[],
        importance=0.5,
    )


def _ctx__event_extraction_concurrency(
    tmp_path: Path, settings: Any = None
) -> tuple[PipelineContext, sqlite3.Connection]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
        JobStatus.VISUAL_ANALYSIS_READY,
        JobStatus.CHARACTERS_READY,
    ):
        manager.transition("job_1", state)
    source = tmp_path / "m.mp4"
    source.write_bytes(b"source-bytes")
    ctx = PipelineContext(
        job_id="job_1",
        movie_path=source,
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=settings if settings is not None else load_settings(),
    )
    return ctx, conn


def _scenes__event_extraction_concurrency(count: int) -> list[Scene]:
    scenes = []
    for index in range(count):
        start = index * 10.0
        scenes.append(
            Scene(scene_id=f"scene_{index:06d}", start=start, end=start + 10.0, duration=10.0)
        )
    return scenes


def _analyses__event_extraction_concurrency(scenes: list[Scene]) -> dict[str, SceneAnalysis]:
    return {
        scene.scene_id: _analysis__event_extraction_concurrency(scene.scene_id) for scene in scenes
    }


# ---------------------------------------------------------------------------
# The configuration
# ---------------------------------------------------------------------------


def test_the_config_default_is_the_stage_default() -> None:
    """The settings fallback, the stage constant and the file all say four."""
    settings = load_settings()
    assert settings.pipeline.event_extraction.concurrency == DEFAULT_CONCURRENCY == 4
    document = read_yaml(repo_root() / "config" / "config.yaml")
    assert document["pipeline"]["event_extraction"]["concurrency"] == 4


# ---------------------------------------------------------------------------
# The stage honours the value
# ---------------------------------------------------------------------------


def test_a_configured_concurrency_caps_the_in_flight_calls(tmp_path: Path) -> None:
    """Six scenes, one batch, a budget of two: no third call ever starts."""
    ctx, conn = _ctx__event_extraction_concurrency(tmp_path)
    try:
        port = _InFlightPort__event_extraction_concurrency()
        scenes = _scenes__event_extraction_concurrency(6)
        run_event_extraction(
            scenes,
            _analyses__event_extraction_concurrency(scenes),
            [],
            [],
            ctx,
            reasoner=port,
            concurrency=2,
        )
        # Two workers, six calls each holding 50 ms: the second is in flight
        # before the first finishes, and the pool never opens a third.
        assert port.max_in_flight == 2
    finally:
        conn.close()


def test_concurrency_one_keeps_the_batch_serial(tmp_path: Path) -> None:
    ctx, conn = _ctx__event_extraction_concurrency(tmp_path)
    try:
        port = _InFlightPort__event_extraction_concurrency()
        scenes = _scenes__event_extraction_concurrency(4)
        run_event_extraction(
            scenes,
            _analyses__event_extraction_concurrency(scenes),
            [],
            [],
            ctx,
            reasoner=port,
            concurrency=1,
        )
        assert port.max_in_flight == 1
    finally:
        conn.close()


def test_a_zero_concurrency_is_rejected(tmp_path: Path) -> None:
    ctx, conn = _ctx__event_extraction_concurrency(tmp_path)
    try:
        scenes = _scenes__event_extraction_concurrency(1)
        with pytest.raises(EventExtractionError, match="concurrency"):
            run_event_extraction(
                scenes,
                _analyses__event_extraction_concurrency(scenes),
                [],
                [],
                ctx,
                reasoner=_InFlightPort__event_extraction_concurrency(),
                concurrency=0,
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The orchestrator passes the configured value through
# ---------------------------------------------------------------------------


def test_the_orchestrator_passes_the_configured_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real stage function hands the file's value to the extraction."""
    settings = load_settings()
    pipeline = settings.pipeline.model_copy(
        update={
            "event_extraction": settings.pipeline.event_extraction.model_copy(
                update={"concurrency": 7}
            )
        }
    )
    settings = settings.model_copy(update={"pipeline": pipeline})
    ctx, conn = _ctx__event_extraction_concurrency(tmp_path, settings)
    try:
        calls: list[dict[str, Any]] = []

        def spy(
            scenes: Any,
            analyses: Any,
            segments: Any,
            characters: Any,
            stage_ctx: Any,
            **kwargs: Any,
        ) -> EventsResult:
            calls.append(kwargs)
            return EventsResult(
                events=[
                    Event(id="event_00001", type=EventType.ACTION, timestamp=1.0, description="x")
                ],
                events_path=ctx.jobs_dir / "events.json",
                cache_hits=0,
                duration_ms=0,
            )

        monkeypatch.setattr("movie_review.story.events.run_event_extraction", spy)

        stage = _get_stage_function("events")
        assert stage is not None, "events stage is missing from the orchestrator"
        for index in (0, 1):
            start = index * 35.0
            scene = Scene(
                scene_id=f"scene_{index:06d}", start=start, end=start + 35.0, duration=35.0
            )
            repo.save_scene(ctx.conn, ctx.job_id, scene)
            repo.save_scene_analysis(
                ctx.conn, ctx.job_id, _analysis__event_extraction_concurrency(scene.scene_id)
            )

        stage(ctx)

        assert calls, "the stage never reached the extraction"
        assert all(call.get("concurrency") == 7 for call in calls)
    finally:
        conn.close()
