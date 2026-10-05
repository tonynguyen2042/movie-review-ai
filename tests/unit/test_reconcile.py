"""T055 acceptance: measured durations drive compress/expand decisions."""

import sqlite3
import wave
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import (
    Claim,
    ClaimType,
    Job,
    JobStatus,
    ReviewParagraph,
    ReviewScript,
    ReviewSection,
)
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.tts.reconcile import (
    ReconcileResult,
    ReconciliationError,
    measure_wav,
    reconcile_script,
    run_reconciliation,
)


def _paragraph(paragraph_id: str, words: int, claims: int = 1) -> ReviewParagraph:
    return ReviewParagraph(
        id=paragraph_id,
        text=" ".join(f"word{n}" for n in range(words)),
        target_seconds=12,
        claims=[
            Claim(
                claim_id=f"{paragraph_id}c{i}",
                text="Fact here.",
                type=ClaimType.PLOT_FACT,
                evidence=["e1"],
            )
            for i in range(claims)
        ],
        visual_intent="shot",
    )


def _script() -> ReviewScript:
    return ReviewScript(
        sections=[
            ReviewSection(
                id="sec_01",
                type="hook",
                paragraphs=[_paragraph("p1", 100, 2), _paragraph("p2", 100, 0)],
            ),
            ReviewSection(id="sec_02", type="climax", paragraphs=[_paragraph("p3", 100, 1)]),
        ]
    )


def _wav(path: Path, seconds: float, rate: int = 16000) -> Path:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00" * frames * 2)
    return path


def test_measure_wav(tmp_path: Path) -> None:
    assert measure_wav(_wav(tmp_path / "a.wav", 2.0)) == pytest.approx(2.0)
    with pytest.raises(ReconciliationError, match="Cannot measure"):
        measure_wav(tmp_path / "absent.wav")


def test_reconcile_ok() -> None:
    result = reconcile_script(_script(), 1190.0, 1200.0, 150)
    assert result.action == "ok"
    assert result.word_count == 300


def test_reconcile_over_compresses() -> None:
    result = reconcile_script(_script(), 200.0, 100.0, 150)
    assert result.action == "compressed"
    assert result.word_count < 300


def test_reconcile_under_requests_expansion() -> None:
    result = reconcile_script(_script(), 100.0, 1200.0, 150)
    assert result.action == "expand-required"
    assert result.word_count == 300


def test_reconcile_bad_inputs() -> None:
    with pytest.raises(ReconciliationError, match="Negative actual"):
        reconcile_script(_script(), -1.0, 1200.0, 150)
    with pytest.raises(ReconciliationError, match="Non-positive target"):
        reconcile_script(_script(), 100.0, 0.0, 150)


@dataclass
class Harness:
    conn: sqlite3.Connection
    ctx: StageContext

    def run(self, script: ReviewScript, narration: Path, target: float = 1200.0) -> ReconcileResult:
        return run_reconciliation(script, narration, target, 150, self.ctx)


def _harness(tmp_path: Path) -> Harness:
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
        JobStatus.REVIEW_PLAN_READY,
        JobStatus.SCRIPT_READY,
    ):
        manager.transition("job_1", state)
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )
    return Harness(conn=conn, ctx=ctx)


def test_run_advances_to_audio_ready(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    narration = _wav(tmp_path / "narration.wav", 1195.0)
    result = harness.run(_script(), narration)
    assert result.action == "ok"
    assert harness.ctx.manager.get("job_1").status is JobStatus.AUDIO_READY
    assert repo.get_artifact(harness.conn, "job_1-review-script") is None


def test_run_compresses_and_persists(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    narration = _wav(tmp_path / "narration.wav", 200.0)
    result = harness.run(_script(), narration, target=100.0)
    assert result.action == "compressed"
    assert harness.ctx.manager.get("job_1").status is JobStatus.AUDIO_READY
    artifact = repo.get_artifact(harness.conn, "job_1-review-script")
    assert artifact is not None
