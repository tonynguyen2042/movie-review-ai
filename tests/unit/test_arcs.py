"""T036 acceptance: story arc extraction with applicable/inapplicable elements."""

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import ModelSpec
from movie_review.domain import Event, EventType, Job, StoryElement
from movie_review.reasoning.port import ReasoningPort
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.story.arcs import ArcsResult, StoryArcError, extract_story_arcs


class _FakeReasoner(ReasoningPort):
    def __init__(self, outputs: Sequence[object]) -> None:
        self._outputs = list(outputs)
        self.fail_on_call = False
        self.unloaded = False

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        if self.fail_on_call:
            raise AssertionError("reasoner must not run on cache hit")
        return json.dumps(self._outputs.pop(0))

    def unload(self) -> None:
        self.unloaded = True


def _events() -> list[Event]:
    return [
        Event(id="event_00001", type=EventType.INTRODUCTION, timestamp=5.0, description="Setup."),
        Event(
            id="event_00002",
            type=EventType.CLIMAX,
            timestamp=90.0,
            description="Showdown.",
            importance=0.95,
        ),
    ]


def _outputs() -> list[object]:
    return [
        [
            {
                "element": "SETUP",
                "applicable": True,
                "description": "Intro.",
                "event_ids": ["event_00001"],
                "confidence": 0.9,
            },
            {
                "element": "CLIMAX",
                "applicable": True,
                "description": "Showdown.",
                "event_ids": ["event_00002"],
                "confidence": 0.95,
            },
            {
                "element": "RESOLUTION",
                "applicable": False,
                "description": "",
                "event_ids": [],
                "confidence": 0.4,
            },
        ]
    ]


def _run(tmp_path: Path, reasoner: _FakeReasoner) -> tuple[sqlite3.Connection, ArcsResult]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    result = extract_story_arcs(
        _events(),
        "char_001: John",
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        cache=CacheManager(tmp_path / "cache"),
        spec=ModelSpec(model="test-reasoning"),
        reasoner=reasoner,
    )
    return conn, result


def test_elements_complete() -> None:
    assert len(StoryElement) == 9
    assert StoryElement["INCITING_INCIDENT"].value == "INCITING_INCIDENT"


def test_happy_path(tmp_path: Path) -> None:
    conn, result = _run(tmp_path, _FakeReasoner(_outputs()))
    assert [a.element.value for a in result.arcs] == ["SETUP", "CLIMAX", "RESOLUTION"]
    assert result.arcs[2].applicable is False
    assert result.cache_hit is False
    assert result.arcs_path.is_file()
    assert repo.get_artifact(conn, "job_1-story-arcs") is not None
    conn.close()


def test_second_run_hits_cache(tmp_path: Path) -> None:
    conn, _ = _run(tmp_path, _FakeReasoner(_outputs()))
    reasoner = _FakeReasoner([])
    reasoner.fail_on_call = True
    result = extract_story_arcs(
        _events(),
        "char_001: John",
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        cache=CacheManager(tmp_path / "cache"),
        spec=ModelSpec(model="test-reasoning"),
        reasoner=reasoner,
    )
    assert result.cache_hit is True
    conn.close()


def test_empty_events_rejected(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    with pytest.raises(StoryArcError, match="must run before"):
        extract_story_arcs(
            [],
            "none",
            job_id="job_1",
            jobs_dir=tmp_path / "jobs",
            conn=conn,
            cache=CacheManager(tmp_path / "cache"),
            spec=ModelSpec(model="m"),
            reasoner=_FakeReasoner([]),
        )
    conn.close()


def test_non_array_rejected(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    with pytest.raises(StoryArcError, match="array"):
        extract_story_arcs(
            _events(),
            "none",
            job_id="job_1",
            jobs_dir=tmp_path / "jobs",
            conn=conn,
            cache=CacheManager(tmp_path / "cache"),
            spec=ModelSpec(model="m"),
            reasoner=_FakeReasoner([{"element": "SETUP"}]),
        )
    conn.close()


def test_applicable_without_events_rejected(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    bad = [
        [
            {
                "element": "SETUP",
                "applicable": True,
                "description": "x",
                "event_ids": [],
                "confidence": 0.9,
            }
        ]
    ]
    with pytest.raises(StoryArcError, match="cites no events"):
        extract_story_arcs(
            _events(),
            "none",
            job_id="job_1",
            jobs_dir=tmp_path / "jobs",
            conn=conn,
            cache=CacheManager(tmp_path / "cache"),
            spec=ModelSpec(model="m"),
            reasoner=_FakeReasoner(bad),
        )
    conn.close()
