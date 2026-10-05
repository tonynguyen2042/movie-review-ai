"""T069 acceptance: quality report assembly and persistence."""

import json
from pathlib import Path

from movie_review.domain import Job, QualityMetric
from movie_review.quality.gates import GateResult
from movie_review.quality.report import build_quality_report
from movie_review.rendering.validate import ValidationCheck, ValidationReport
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _metrics() -> list[QualityMetric]:
    return [
        QualityMetric(name="evidence_coverage", score=96.0, threshold=90.0),
        QualityMetric(name="timeline_consistency", score=80.0, threshold=95.0),
    ]


def _gate() -> GateResult:
    return GateResult(passed=False, metrics=_metrics(), failures=["timeline_consistency"])


def _validation() -> ValidationReport:
    return ValidationReport(
        checks=[
            ValidationCheck("video.present", True),
            ValidationCheck("audio.present", False, "missing"),
        ]
    )


def test_full_assembly(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "q.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    result = build_quality_report(
        "job_1", _metrics(), _gate(), _validation(), tmp_path / "jobs", conn
    )
    assert result.report.passed is False
    assert result.report.overall == 88.0
    assert result.report_path.is_file()
    document = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert document["gate"] == {"passed": False, "failures": ["timeline_consistency"]}
    assert document["validation"] == {"ok": False, "failures": ["audio.present"]}
    assert document["metrics"][0]["name"] == "evidence_coverage"
    artifact = repo.get_artifact(conn, "job_1-quality-report")
    assert artifact is not None
    assert artifact.stage == "quality"
    conn.close()


def test_minimal_assembly(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "q.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    result = build_quality_report("job_1", _metrics(), None, None, tmp_path / "jobs", conn)
    document = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert document["gate"] is None
    assert document["validation"] is None
    assert result.report.passed is False
    conn.close()
