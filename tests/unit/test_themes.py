"""T037 acceptance: grounded theme extraction."""

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.domain import Event, EventType, Job
from movie_review.reasoning.port import ReasoningPort
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.story.themes import ThemeExtractionError, ThemesResult, extract_themes


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


def _events() -> list[Event]:
    return [
        Event(
            id="event_00001",
            type=EventType.BETRAYAL,
            timestamp=50.0,
            description="Sarah lies.",
            importance=0.9,
        ),
    ]


def _run(tmp_path: Path, reasoner: _FakeReasoner) -> tuple[sqlite3.Connection, ThemesResult]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    result = extract_themes(
        _events(),
        "char_001: John",
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        cache=CacheManager(tmp_path / "cache"),
        model="test-reasoning",
        reasoner=reasoner,
    )
    return conn, result


def _outputs() -> list[object]:
    return [
        [
            {"theme": "betrayal", "evidence": ["event_00001"], "confidence": 0.85},
            {"theme": "trust", "evidence": ["event_00001"], "confidence": 0.6},
        ]
    ]


def test_happy_path(tmp_path: Path) -> None:
    conn, result = _run(tmp_path, _FakeReasoner(_outputs()))
    assert [t.theme for t in result.themes] == ["betrayal", "trust"]
    assert result.cache_hit is False
    assert result.themes_path.is_file()
    assert repo.get_artifact(conn, "job_1-themes") is not None
    conn.close()


def test_second_run_hits_cache(tmp_path: Path) -> None:
    conn, _ = _run(tmp_path, _FakeReasoner(_outputs()))
    conn.close()
    reasoner = _FakeReasoner([])
    reasoner.fail_on_call = True
    conn2, result = _run(tmp_path, reasoner)
    assert result.cache_hit is True
    conn2.close()


def test_empty_events_rejected(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    with pytest.raises(ThemeExtractionError, match="must run before"):
        extract_themes(
            [],
            "none",
            job_id="job_1",
            jobs_dir=tmp_path / "jobs",
            conn=conn,
            cache=CacheManager(tmp_path / "cache"),
            model="m",
            reasoner=_FakeReasoner([]),
        )
    conn.close()


def test_unevidenced_theme_rejected(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    bad = [[{"theme": "love", "evidence": [], "confidence": 0.9}]]
    with pytest.raises(ThemeExtractionError, match="cites no evidence"):
        extract_themes(
            _events(),
            "none",
            job_id="job_1",
            jobs_dir=tmp_path / "jobs",
            conn=conn,
            cache=CacheManager(tmp_path / "cache"),
            model="m",
            reasoner=_FakeReasoner(bad),
        )
    conn.close()
