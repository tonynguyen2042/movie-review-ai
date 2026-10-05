"""T095 acceptance: QC report UI loads and exports data."""

import json
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.ui.qc_report import QualityReportUI


def _write_report(job_dir: Path, report: dict) -> None:
    (job_dir / "qc").mkdir(parents=True, exist_ok=True)
    artifacts.write_json(job_dir / "qc" / "quality-report.json", report)


def test_qc_report_ui_from_artifact(tmp_path: Path) -> None:
    """QC report UI can be built from quality-report.json."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_qc"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()

    report = {
        "job_id": job_id,
        "passed": True,
        "overall": 88.5,
        "metrics": [
            {
                "name": "evidence_coverage",
                "score": 92.0,
                "threshold": 90.0,
                "detail": "9/10 claims",
            },
            {
                "name": "timeline_consistency",
                "score": 85.0,
                "threshold": 95.0,
                "detail": "one mismatch",
            },
        ],
        "gate": {"passed": False, "failures": ["timeline_consistency below threshold"]},
        "validation": {"ok": True, "failures": []},
    }
    _write_report(job_dir, report)

    ui = QualityReportUI(jobs_dir, job_id)
    data = ui.load()

    assert data["job_id"] == job_id
    assert data["passed"] is True
    assert data["overall"] == 88.5
    assert data["metric_count"] == 2
    assert data["passed_count"] == 1
    assert data["failed_count"] == 1

    evidence = next(m for m in data["metrics"] if m["name"] == "evidence_coverage")
    assert evidence["passed"] is True
    timeline = next(m for m in data["metrics"] if m["name"] == "timeline_consistency")
    assert timeline["passed"] is False

    assert data["gate"]["passed"] is False
    assert data["gate"]["failures"] == ["timeline_consistency below threshold"]
    assert data["validation"]["ok"] is True


def test_qc_report_ui_json_export(tmp_path: Path) -> None:
    """QC report UI can export to JSON."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_json"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()

    report = {
        "job_id": job_id,
        "passed": False,
        "overall": 42.0,
        "metrics": [{"name": "evidence_coverage", "score": 42.0, "threshold": 90.0, "detail": ""}],
    }
    _write_report(job_dir, report)

    ui = QualityReportUI(jobs_dir, job_id)
    data = json.loads(ui.to_json())

    assert data["job_id"] == job_id
    assert data["passed"] is False
    assert data["metrics"][0]["score"] == 42.0


def test_qc_report_ui_html_export(tmp_path: Path) -> None:
    """QC report UI can export to HTML."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_html"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()

    report = {
        "job_id": job_id,
        "passed": True,
        "overall": 95.0,
        "metrics": [
            {"name": "evidence_coverage", "score": 95.0, "threshold": 90.0, "detail": "good"}
        ],
        "gate": {"passed": True, "failures": []},
        "validation": {"ok": True, "failures": []},
    }
    _write_report(job_dir, report)

    ui = QualityReportUI(jobs_dir, job_id)
    html = ui.to_html()

    assert "QC Report" in html
    assert "Job" in html
    assert "Quality Metrics" in html
    assert "evidence_coverage" in html
    assert "data = " in html


def test_qc_report_ui_empty(tmp_path: Path) -> None:
    """QC report UI returns empty structure when no report exists."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_empty"
    (jobs_dir / job_id).mkdir()

    ui = QualityReportUI(jobs_dir, job_id)
    data = ui.load()

    assert data["job_id"] == job_id
    assert data["passed"] is False
    assert data["overall"] == 0.0
    assert data["metric_count"] == 0
    assert data["metrics"] == []
    assert len(data["gate"]["failures"]) == 0
