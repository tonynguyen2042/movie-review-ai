"""T074 acceptance: model benchmark harness measures injected operations."""

from movie_review.benchmark.models import benchmark_operation


def test_benchmark_reports_latency() -> None:
    calls = 0

    def fake() -> int:
        nonlocal calls
        calls += 1
        return 100

    result = benchmark_operation("asr", "whisper-large-v3-turbo", fake, repeats=3)
    assert result.repeats == 3 and calls == 3
    assert result.mean_seconds >= 0
    assert result.throughput_per_sec >= 0


def test_benchmark_rejects_zero_repeats() -> None:
    try:
        benchmark_operation("asr", "m", lambda: 1, repeats=0)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
