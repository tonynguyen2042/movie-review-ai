"""T075 acceptance: pipeline benchmark times stages and totals."""

import pytest

from movie_review.benchmark.pipeline import benchmark_pipeline


def test_pipeline_benchmark_times_stages() -> None:
    report = benchmark_pipeline({"ingest": lambda: 1, "scenes": lambda: 2})
    assert [item.stage for item in report.stages] == ["ingest", "scenes"]
    assert report.total_seconds >= 0
    assert report.slowest() is not None


def test_pipeline_benchmark_rejects_empty() -> None:
    with pytest.raises(ValueError):
        benchmark_pipeline({})
