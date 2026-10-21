"""T038 acceptance: evidenced twist detection rejects unsupported twists."""

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import ModelSpec
from movie_review.domain import Event, EventType, Job
from movie_review.reasoning.port import ReasoningPort
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.story.twists import TwistExtractionError, TwistsResult, extract_twists


class _FakeReasoner(ReasoningPort):
    def __init__(self, outputs: Sequence[object]) -> None:
        self._outputs = list(outputs)
        self.fail_on_call = False

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        if self.fail_on_call:
            raise AssertionError("reasoner must not run on cache hit")
        return json.dumps(self._outputs.pop(0))

    def unload(self) -> None:
        pass


def _events__twists() -> list[Event]:
    return [
        Event(id="event_00001", type=EventType.INTRODUCTION, timestamp=5.0, description="Arrival."),
        Event(
            id="event_00002",
            type=EventType.REVELATION,
            timestamp=90.0,
            description="He was dead.",
            importance=0.95,
        ),
    ]


def _run__twists(
    tmp_path: Path, reasoner: _FakeReasoner
) -> tuple[sqlite3.Connection, TwistsResult]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    result: TwistsResult = extract_twists(
        _events__twists(),
        "char_001: John",
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        cache=CacheManager(tmp_path / "cache"),
        spec=ModelSpec(model="test-reasoning"),
        reasoner=reasoner,
    )
    return conn, result


def _twist(description: str, refs: list[str]) -> list[object]:
    return [
        [
            {
                "description": description,
                "revealed_at": 90.0,
                "foreshadowed_by": refs,
                "confidence": 0.88,
            }
        ]
    ]


def test_happy_path(tmp_path: Path) -> None:
    conn, result = _run__twists(
        tmp_path, _FakeReasoner(_twist("He was dead.", ["event_00001", "event_00002"]))
    )
    assert [t.id for t in result.twists] == ["twist_001"]
    assert result.cache_hit is False
    assert result.twists_path.is_file()
    assert repo.get_artifact(conn, "job_1-twists") is not None
    conn.close()


def test_second_run_hits_cache(tmp_path: Path) -> None:
    conn, _ = _run__twists(tmp_path, _FakeReasoner(_twist("x", ["event_00001", "event_00002"])))
    conn.close()
    reasoner = _FakeReasoner([])
    reasoner.fail_on_call = True
    conn2, result = _run__twists(tmp_path, reasoner)
    assert result.cache_hit is True
    conn2.close()


def test_unknown_foreshadowing_rejected(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    with pytest.raises(TwistExtractionError, match="unknown events"):
        extract_twists(
            _events__twists(),
            "none",
            job_id="job_1",
            jobs_dir=tmp_path / "jobs",
            conn=conn,
            cache=CacheManager(tmp_path / "cache"),
            spec=ModelSpec(model="m"),
            reasoner=_FakeReasoner(_twist("x", ["event_00001", "event_999"])),
        )
    conn.close()


def test_single_foreshadowing_rejected(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    with pytest.raises(TwistExtractionError, match="at least 2"):
        extract_twists(
            _events__twists(),
            "none",
            job_id="job_1",
            jobs_dir=tmp_path / "jobs",
            conn=conn,
            cache=CacheManager(tmp_path / "cache"),
            spec=ModelSpec(model="m"),
            reasoner=_FakeReasoner(_twist("x", ["event_00001"])),
        )
    conn.close()


def test_empty_events_rejected(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    with pytest.raises(TwistExtractionError, match="must run before"):
        extract_twists(
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
