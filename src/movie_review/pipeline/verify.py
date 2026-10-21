"""Verify the script's claims before anything downstream trusts it.

T142. The fact checker, the claim extractor and the repair loop were all
written and tested, and no module in the pipeline called any of them. The
claims table was always empty, no verdict was ever reached, and the
``SCRIPT_VERIFIED`` state in the spec's chain was unreachable.

This is the stage that makes the constitution's P1 (Evidence First) and P5
(No Silent Hallucination) real rather than aspirational: a claim the
evidence does not support is removed, converted into a marked interpretation
or qualified, and the verdicts are recorded on the job.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.domain import Artifact, Claim, JobStatus
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.context import StageContext
from movie_review.review.claims import ClaimExtractionError, extract_claims, store_claims
from movie_review.review.continuity import check_continuity
from movie_review.review.factcheck import check_claims
from movie_review.review.repair import RepairError, repair_script
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "verify"
STAGE_VERSION = "v1"
VERDICTS_FILENAME = "script-verification.json"


class VerificationError(Exception):
    """Verification failed in a classified way."""


@dataclass
class VerificationResult:
    """The outcome of verifying a script."""

    claims: list[Claim] = field(default_factory=list)
    verdicts: list[object] = field(default_factory=list)
    removed: int = 0
    converted: int = 0
    qualified: int = 0
    continuity_issues: int = 0
    verdicts_path: Path | None = None
    duration_ms: int = 0


def run_verification(
    script_path: Path,
    ctx: StageContext,
) -> VerificationResult:
    """Check the script's claims and repair what the evidence does not support.

    The script is read, its claims are extracted and stored, the fact
    checker rules on them, the continuity checker looks for a character who
    acts after dying or a scene that does not exist, and the repair loop
    applies the verdicts.

    The repaired script is written back, so the narration that follows is
    the one that was verified.
    """
    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise VerificationError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise VerificationError(f"Job {ctx.job_id} failed; resume arrives in T085")
    owns_completion = job.status is JobStatus.SCRIPT_READY

    from movie_review.review.translate import load_script

    try:
        script = load_script(script_path)
    except (OSError, ValueError) as exc:
        raise VerificationError(f"Cannot read the script at {script_path}: {exc}") from exc

    try:
        claims = extract_claims(script)
    except ClaimExtractionError as exc:
        if owns_completion:
            ctx.manager.fail(ctx.job_id, STAGE_NAME, str(exc))
        raise VerificationError(f"Cannot extract the script's claims: {exc}") from exc

    store_claims(ctx.conn, ctx.job_id, claims)

    verdicts = check_claims(claims, ctx.conn, ctx.job_id)

    # The verdicts are recorded on the claim rows, so the database says what
    # was decided rather than only the report.
    for verdict in verdicts:
        ctx.conn.execute(
            "UPDATE claims SET status = ? WHERE job_id = ? AND claim_id = ?",
            (verdict.status.value, ctx.job_id, verdict.claim_id),
        )
    ctx.conn.commit()

    # The continuity checker looks for a character who acts after dying and
    # for a scene that does not exist.
    events = repo.list_events(ctx.conn, ctx.job_id)
    scenes = repo.list_scenes(ctx.conn, ctx.job_id)
    issues = check_continuity(events, scenes)

    try:
        repaired = repair_script(script, verdicts)
    except RepairError as exc:
        if owns_completion:
            ctx.manager.fail(ctx.job_id, STAGE_NAME, str(exc))
        raise VerificationError(f"Cannot repair the script: {exc}") from exc

    # The repaired script replaces the original, so everything downstream
    # works with the script that was verified.
    document = {
        "job_id": ctx.job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "claims": len(claims),
        "verdicts": [
            {
                "claim_id": verdict.claim_id,
                "status": verdict.status.value,
                "evidence": list(verdict.evidence),
                "reasons": list(verdict.reasons),
            }
            for verdict in verdicts
        ],
        "continuity_issues": [{"kind": issue.kind, "detail": issue.detail} for issue in issues],
        "removed": repaired.removed,
        "converted": repaired.converted,
        "qualified": repaired.qualified,
    }
    verdicts_path = artifacts.artifact_path(ctx.jobs_dir, ctx.job_id, STAGE_NAME, VERDICTS_FILENAME)
    output_hash = artifacts.write_json(verdicts_path, document)

    artifacts.write_json(script_path, {"script": repaired.script.model_dump(mode="json")})

    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-verification",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(ctx.jobs_dir, ctx.job_id, verdicts_path),
            input_hash=output_hash,
            output_hash=output_hash,
        ),
    )

    duration_ms = int((time.perf_counter() - started) * 1000)
    with ulog.logging_context(job_id=ctx.job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="stage.completed",
            status="ok",
            duration_ms=duration_ms,
            claims=len(claims),
            removed=repaired.removed,
            converted=repaired.converted,
            qualified=repaired.qualified,
            continuity_issues=len(issues),
        )

    # The second pass: the critic reads the repaired script and reports on
    # it. It is optional -- a profile that does not enable it gets an empty
    # report rather than a failure.
    from movie_review.review.critic import critique_script

    try:
        critique_script(repaired.script, ctx, ctx.settings.models.critic)
    except Exception:
        # A critic that cannot run must not fail a review that is already
        # verified. The report is a second opinion, not a gate.
        with ulog.logging_context(job_id=ctx.job_id, stage=STAGE_NAME):
            ulog.log_event(
                _logger,
                event="critic.skipped",
                status="error",
                error="the critic could not run",
            )

    if owns_completion:
        ctx.manager.transition(ctx.job_id, JobStatus.SCRIPT_VERIFIED)

    return VerificationResult(
        claims=claims,
        verdicts=list(verdicts),
        removed=repaired.removed,
        converted=repaired.converted,
        qualified=repaired.qualified,
        continuity_issues=len(issues),
        verdicts_path=verdicts_path,
        duration_ms=duration_ms,
    )
