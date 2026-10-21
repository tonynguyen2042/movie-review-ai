"""The verify stage must be able to fail a claim and repair the script.

T142. The claim extractor, the fact checker and the repair loop were all
written and tested, and no module in the pipeline called any of them. The
claims table was always empty, no verdict was ever reached, and the
`SCRIPT_VERIFIED` state in the spec's chain was unreachable.

This is the stage that makes the constitution's P1 (Evidence First) and P5
(No Silent Hallucination) real: a claim the evidence does not support is
removed, converted into a marked interpretation or qualified.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import (
    Claim,
    ClaimStatus,
    ClaimType,
    Event,
    EventType,
    Job,
    JobStatus,
    ReviewParagraph,
    ReviewScript,
    ReviewSection,
    Scene,
)
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.pipeline.verify import run_verification
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _paragraph__verify_stage(
    paragraph_id: str, text: str, claim_text: str, evidence: list[str]
) -> ReviewParagraph:
    return ReviewParagraph(
        id=paragraph_id,
        text=text,
        target_seconds=12,
        claims=[
            Claim(
                claim_id=f"{paragraph_id}-c1",
                text=claim_text,
                type=ClaimType.PLOT_FACT,
                evidence=evidence,
                confidence=0.9,
            )
        ],
        visual_intent="establishing shot",
    )


def _script__verify_stage(
    paragraph_id: str = "p1", evidence: list[str] | None = None
) -> ReviewScript:
    return ReviewScript(
        sections=[
            ReviewSection(
                id="sec_001",
                type="hook",
                paragraphs=[
                    _paragraph__verify_stage(
                        paragraph_id,
                        "The hero walks in.",
                        "The hero finds the photograph.",
                        evidence if evidence is not None else ["event_00001"],
                    )
                ],
            )
        ]
    )


def _ctx__verify_stage(tmp_path: Path) -> tuple[StageContext, sqlite3.Connection]:
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
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
    )
    return ctx, conn


def _script_path(tmp_path: Path, script: ReviewScript) -> Path:
    path = tmp_path / "jobs" / "job_1" / "review" / "review-script.json"
    artifacts.write_json(path, {"script": script.model_dump(mode="json")})
    return path


def _seed_evidence(conn: sqlite3.Connection) -> None:
    repo.save_event(
        conn,
        "job_1",
        Event(
            id="event_00001",
            type=EventType.DISCOVERY,
            timestamp=10.0,
            description="The hero finds the photograph.",
        ),
    )
    repo.save_scene(
        conn, "job_1", Scene(scene_id="scene_000001", start=0.0, end=60.0, duration=60.0)
    )


def test_the_claims_are_extracted_and_stored(tmp_path: Path) -> None:
    """The claims table was always empty before this stage existed."""
    ctx, conn = _ctx__verify_stage(tmp_path)
    try:
        _seed_evidence(conn)
        path = _script_path(tmp_path, _script__verify_stage())
        result = run_verification(path, ctx)

        assert len(result.claims) == 1
        stored = repo.list_claims(conn, "job_1")
        assert len(stored) == 1
        assert stored[0].claim_id == "p1-c1"
    finally:
        conn.close()


def test_a_supported_claim_is_kept_and_the_job_is_verified(tmp_path: Path) -> None:
    """A claim the evidence supports stays, and the job moves on."""
    ctx, conn = _ctx__verify_stage(tmp_path)
    try:
        _seed_evidence(conn)
        path = _script_path(tmp_path, _script__verify_stage())
        result = run_verification(path, ctx)

        assert result.removed == 0
        assert result.converted == 0
        assert ctx.manager.get("job_1").status is JobStatus.SCRIPT_VERIFIED
    finally:
        conn.close()


def test_an_unsupported_claim_is_converted_to_an_interpretation(tmp_path: Path) -> None:
    """A factual claim with no evidence must not stay a fact."""
    ctx, conn = _ctx__verify_stage(tmp_path)
    try:
        _seed_evidence(conn)
        # The claim cites an event that does not exist.
        path = _script_path(tmp_path, _script__verify_stage(evidence=["event_does_not_exist"]))
        result = run_verification(path, ctx)

        assert result.converted == 1
        assert ctx.manager.get("job_1").status is JobStatus.SCRIPT_VERIFIED

        # The repaired script is what the narration will use.
        document = artifacts.read_json(path)
        claims = document["script"]["sections"][0]["paragraphs"][0]["claims"]
        assert claims[0]["type"] == "INTERPRETATION"
    finally:
        conn.close()


def test_the_verdicts_are_recorded_on_the_job(tmp_path: Path) -> None:
    """The database must say what was decided, not only the report."""
    ctx, conn = _ctx__verify_stage(tmp_path)
    try:
        _seed_evidence(conn)
        path = _script_path(tmp_path, _script__verify_stage(evidence=["event_does_not_exist"]))
        run_verification(path, ctx)

        stored = repo.list_claims(conn, "job_1")
        assert stored[0].status is ClaimStatus.INSUFFICIENT_EVIDENCE
    finally:
        conn.close()


def test_the_verdicts_are_written_to_a_report(tmp_path: Path) -> None:
    """The report is the artifact of record for the stage."""
    ctx, conn = _ctx__verify_stage(tmp_path)
    try:
        _seed_evidence(conn)
        path = _script_path(tmp_path, _script__verify_stage())
        result = run_verification(path, ctx)

        assert result.verdicts_path is not None
        assert result.verdicts_path.is_file()
        assert result.verdicts_path is not None
        document = artifacts.read_json(result.verdicts_path)
        assert document["claims"] == 1
        assert len(document["verdicts"]) == 1
        assert "verdicts" in document
    finally:
        conn.close()


def test_the_continuity_checker_runs(tmp_path: Path) -> None:
    """The continuity findings reach the report."""
    ctx, conn = _ctx__verify_stage(tmp_path)
    try:
        _seed_evidence(conn)
        path = _script_path(tmp_path, _script__verify_stage())
        result = run_verification(path, ctx)
        assert result.continuity_issues == 0
        assert result.verdicts_path is not None
        document = artifacts.read_json(result.verdicts_path)
        assert document["continuity_issues"] == []
    finally:
        conn.close()


def test_the_stage_is_in_the_pipeline(tmp_path: Path) -> None:
    """A stage nobody can reach is not a stage."""
    from movie_review.pipeline.orchestrator import STAGE_SEQUENCE

    order = [name for name, _ in STAGE_SEQUENCE]
    assert "verify" in order
    assert order.index("verify") == order.index("review") + 1
