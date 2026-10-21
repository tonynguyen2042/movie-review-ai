"""T044 acceptance: script writer follows outline with validated claims."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import ModelSpec, load_settings
from movie_review.domain import Job, JobStatus, OutlineSection, ReviewPlan
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.reasoning.port import ReasoningPort
from movie_review.review.styles import load_style
from movie_review.review.writer import ScriptResult, ScriptWriterError, write_script
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


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


def _section(section_id: str, section_type: str, text: str) -> dict[str, object]:
    return {
        "sections": [
            {
                "id": section_id,
                "type": section_type,
                "paragraphs": [
                    {
                        "id": f"{section_id}p1",
                        "text": text,
                        "target_seconds": 12,
                        "claims": [
                            {
                                "claim_id": f"{section_id}c1",
                                "text": text,
                                "type": "PLOT_FACT",
                                "evidence": ["event_00001"],
                                "confidence": 0.9,
                            }
                        ],
                        "visual_intent": "establishing shot",
                    }
                ],
            }
        ]
    }


@dataclass
class Harness:
    conn: sqlite3.Connection
    ctx: StageContext
    reasoner: _FakeReasoner
    outline: ReviewPlan
    analysis: dict[str, object]

    def write(self) -> ScriptResult:
        return write_script(
            self.outline,
            self.analysis,
            load_style("youtube"),
            100,
            self.ctx,
            ModelSpec(model="test-reasoning"),
            reasoner=self.reasoner,
        )


def _harness__writer(tmp_path: Path, outputs: Sequence[object]) -> Harness:
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
            ),
            OutlineSection(
                id="section_02",
                type="climax",
                target_seconds=150,
                event_ids=["event_00002"],
                purpose="climax",
            ),
        ],
        total_seconds=190,
    )
    analysis: dict[str, object] = {
        "events": [
            {"id": "event_00001", "timestamp": 5.0, "description": "Arrival."},
            {"id": "event_00002", "timestamp": 90.0, "description": "Showdown."},
        ],
        "characters": ["char_001"],
        "themes": [],
        "twists": [],
    }
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )
    return Harness(
        conn=conn, ctx=ctx, reasoner=_FakeReasoner(outputs), outline=outline, analysis=analysis
    )


def _outputs__writer() -> list[object]:
    return [
        _section("section_01", "hook", "What if everything you knew was wrong"),
        _section("section_02", "climax", "The confrontation changes everything"),
    ]


def test_happy_path(tmp_path: Path) -> None:
    harness = _harness__writer(tmp_path, _outputs__writer())
    result = harness.write()
    assert [s.type for s in result.script.sections] == ["hook", "climax"]
    assert result.word_count > 0
    assert result.cache_hits == 0
    assert result.script_path.is_file()
    assert harness.reasoner.unloaded is True
    assert harness.ctx.manager.get("job_1").status is JobStatus.SCRIPT_READY
    assert repo.get_artifact(harness.conn, "job_1-review-script") is not None


def test_second_run_hits_cache(tmp_path: Path) -> None:
    harness = _harness__writer(tmp_path, _outputs__writer())
    harness.write()
    harness.reasoner.fail_on_call = True
    result = harness.write()
    assert result.cache_hits == 2


def test_order_violation_fails_job(tmp_path: Path) -> None:
    bad = [
        _section("section_01", "climax", "Wrong order here"),
        _section("section_02", "hook", "Wrong order here"),
    ]
    harness = _harness__writer(tmp_path, bad)
    with pytest.raises(ScriptWriterError, match="order violated"):
        harness.write()
    job = harness.ctx.manager.get("job_1")
    assert job.status is JobStatus.FAILED
    assert job.failed_stage == "review"


def test_bad_claim_type_fails_job(tmp_path: Path) -> None:
    payload = _section("section_01", "hook", "Some text here")
    payload["sections"][0]["paragraphs"][0]["claims"][0]["type"] = "MADE_UP"  # type: ignore[index]
    harness = _harness__writer(tmp_path, [payload, _section("section_02", "climax", "More text")])
    with pytest.raises(ScriptWriterError, match="Invalid section"):
        harness.write()
    assert harness.ctx.manager.get("job_1").status is JobStatus.FAILED


def test_unknown_job(tmp_path: Path) -> None:
    harness = _harness__writer(tmp_path, _outputs__writer())
    harness.ctx.job_id = "job_2"
    with pytest.raises(ScriptWriterError, match="Unknown job"):
        harness.write()


def test_failed_job_rejected(tmp_path: Path) -> None:
    harness = _harness__writer(tmp_path, _outputs__writer())
    harness.ctx.manager.fail("job_1", "story", "earlier")
    with pytest.raises(ScriptWriterError, match="failed"):
        harness.write()


def test_bad_target_words(tmp_path: Path) -> None:
    harness = _harness__writer(tmp_path, _outputs__writer())
    with pytest.raises(ScriptWriterError, match="positive"):
        write_script(
            harness.outline,
            harness.analysis,
            load_style("youtube"),
            0,
            harness.ctx,
            ModelSpec(model="m"),
            reasoner=harness.reasoner,
        )


def test_rerun_past_script_ready(tmp_path: Path) -> None:
    harness = _harness__writer(tmp_path, _outputs__writer())
    harness.write()
    harness.ctx.manager.transition("job_1", JobStatus.SCRIPT_VERIFIED)
    harness.reasoner.fail_on_call = True
    result = harness.write()
    assert result.cache_hits == 2
    assert harness.ctx.manager.get("job_1").status is JobStatus.SCRIPT_VERIFIED
