"""Quality report assembly: metrics + gate + validation → JSON (T069).

Persists ``qc/quality-report.json`` with an artifact record. Metric
computation (T064-T067), gating (T068), and render validation (T062) supply
the inputs; this module only assembles and stores.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from movie_review.artifacts import manager as artifacts
from movie_review.domain import Artifact, QualityMetric, QualityReport
from movie_review.quality.gates import GateResult
from movie_review.rendering.validate import ValidationReport
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "quality"
REPORT_FILENAME = "quality-report.json"


@dataclass(frozen=True)
class QualityReportResult:
    """Assembled report with its artifact path."""

    report: QualityReport
    report_path: Path


def build_quality_report(
    job_id: str,
    metrics: list[QualityMetric],
    gate: GateResult | None,
    validation: ValidationReport | None,
    jobs_dir: str | Path,
    conn: sqlite3.Connection,
) -> QualityReportResult:
    """Assemble, persist, and record the quality report."""
    report = QualityReport(job_id=job_id, metrics=list(metrics))
    document: dict[str, Any] = {
        "job_id": job_id,
        "passed": report.passed,
        "overall": report.overall,
        "metrics": [metric.model_dump(mode="json") for metric in report.metrics],
        "gate": {
            "passed": gate.passed,
            "failures": list(gate.failures),
        }
        if gate is not None
        else None,
        "validation": {
            "ok": validation.ok,
            "failures": [check.name for check in validation.failures()],
        }
        if validation is not None
        else None,
    }
    report_path = artifacts.artifact_path(jobs_dir, job_id, "qc", REPORT_FILENAME)
    output_hash = artifacts.write_json(report_path, document)
    repo.save_artifact(
        conn,
        Artifact(
            artifact_id=f"{job_id}-quality-report",
            job_id=job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(jobs_dir, job_id, report_path),
            input_hash=output_hash,
            output_hash=output_hash,
        ),
    )
    with ulog.logging_context(job_id=job_id, stage=STAGE_NAME):
        ulog.log_event(_logger, event="report.completed", status="ok")
    return QualityReportResult(report=report, report_path=report_path)
