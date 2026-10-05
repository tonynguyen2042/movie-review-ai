"""T063 acceptance: QC metric bounds and report semantics."""

import pytest
from pydantic import ValidationError

from movie_review.domain import QualityMetric, QualityReport


def test_bounds() -> None:
    QualityMetric(name="m", score=100.0, threshold=100.0)
    with pytest.raises(ValidationError):
        QualityMetric(name="m", score=100.1)
    with pytest.raises(ValidationError):
        QualityMetric(name="m", score=-0.1)
    with pytest.raises(ValidationError):
        QualityMetric(name="", score=50.0)


def test_metric_passed() -> None:
    assert QualityMetric(name="m", score=90.0, threshold=90.0).passed is True
    assert QualityMetric(name="m", score=89.9, threshold=90.0).passed is False


def test_report_semantics() -> None:
    empty = QualityReport(job_id="job_1")
    assert empty.passed is False
    assert empty.overall == 0.0
    report = QualityReport(
        job_id="job_1",
        metrics=[
            QualityMetric(name="a", score=90.0, threshold=80.0),
            QualityMetric(name="b", score=70.0, threshold=80.0),
        ],
    )
    assert report.passed is False
    assert report.overall == pytest.approx(80.0)
    assert [m.name for m in report.failures()] == ["b"]
    passing = QualityReport(
        job_id="job_1", metrics=[QualityMetric(name="a", score=95.0, threshold=80.0)]
    )
    assert passing.passed is True


def test_round_trip() -> None:
    report = QualityReport(
        job_id="job_1", metrics=[QualityMetric(name="a", score=50.0, detail="half")]
    )
    assert QualityReport.model_validate(report.model_dump(mode="json")) == report
