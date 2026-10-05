"""TTS duration reconciliation (T055, spec sections 47 and 93).

Compares measured narration audio against the target: within tolerance it
passes; over target it compresses low-value paragraphs via T050 (never
pads); under target it flags expansion for the writer. Owns the
``SCRIPT_READY`` → ``SCRIPT_VERIFIED`` → ``AUDIO_READY`` lifecycle path
since verification (T047-T049) is pure.
"""

from __future__ import annotations

import logging
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.domain import Artifact, JobStatus, ReviewScript
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.context import StageContext
from movie_review.review.duration import fit_script, script_words, target_words
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "tts"
STAGE_VERSION = "v1"
TOLERANCE_RATIO = 0.02


class ReconciliationError(Exception):
    """Reconciliation failed in a classified way."""


@dataclass(frozen=True)
class ReconcileResult:
    """Reconciliation outcome with the effective script."""

    script: ReviewScript
    action: str
    actual_seconds: float
    target_seconds: float
    word_count: int


def measure_wav(path: str | Path) -> float:
    """Measured duration of a WAV file in seconds."""
    try:
        with wave.open(str(path), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
    except (wave.Error, OSError) as exc:
        raise ReconciliationError(f"Cannot measure {path}: {exc}") from exc
    if rate <= 0:
        raise ReconciliationError(f"Invalid WAV rate in {path}")
    return frames / rate


def reconcile_script(
    script: ReviewScript,
    actual_seconds: float,
    target_seconds: float,
    wpm: int,
) -> ReconcileResult:
    """Decide ok/compress/expand from measured audio against the target."""
    if actual_seconds < 0:
        raise ReconciliationError(f"Negative actual duration: {actual_seconds}")
    if target_seconds <= 0:
        raise ReconciliationError(f"Non-positive target: {target_seconds}")
    tolerance = max(0.5, target_seconds * TOLERANCE_RATIO)
    if abs(actual_seconds - target_seconds) <= tolerance:
        return ReconcileResult(
            script=script,
            action="ok",
            actual_seconds=actual_seconds,
            target_seconds=target_seconds,
            word_count=script_words(script),
        )
    if actual_seconds < target_seconds:
        return ReconcileResult(
            script=script,
            action="expand-required",
            actual_seconds=actual_seconds,
            target_seconds=target_seconds,
            word_count=script_words(script),
        )
    fitted = fit_script(script, target_words(target_seconds, wpm))
    return ReconcileResult(
        script=fitted.script,
        action="compressed",
        actual_seconds=actual_seconds,
        target_seconds=target_seconds,
        word_count=fitted.word_count,
    )


def run_reconciliation(
    script: ReviewScript,
    narration_path: str | Path,
    target_seconds: float,
    wpm: int,
    ctx: StageContext,
) -> ReconcileResult:
    """Measure narration, reconcile, persist, and advance to ``AUDIO_READY``."""
    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise ReconciliationError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise ReconciliationError(f"Job {ctx.job_id} failed; resume arrives in T085")
    owns_completion = job.status is JobStatus.SCRIPT_READY

    actual = measure_wav(narration_path)
    result = reconcile_script(script, actual, target_seconds, wpm)
    if result.action == "compressed":
        script_path = artifacts.artifact_path(
            ctx.jobs_dir, ctx.job_id, "review", "review-script.json"
        )
        output_hash = artifacts.write_json(script_path, result.script.model_dump(mode="json"))
        repo.save_artifact(
            ctx.conn,
            Artifact(
                artifact_id=f"{ctx.job_id}-review-script",
                job_id=ctx.job_id,
                stage="review",
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
            action=result.action,
        )
    if owns_completion:
        ctx.manager.transition(ctx.job_id, JobStatus.SCRIPT_VERIFIED)
        ctx.manager.transition(ctx.job_id, JobStatus.AUDIO_READY)
    return result
