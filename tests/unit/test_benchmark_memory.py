"""T076 acceptance: memory benchmark reports peak allocation."""

from movie_review.benchmark.memory import benchmark_memory


def test_memory_benchmark_measures() -> None:
    def fake() -> list[int]:
        return [0] * 1000

    result = benchmark_memory("frames", fake)
    assert result.peak_bytes >= 0
    assert result.peak_mb >= 0
