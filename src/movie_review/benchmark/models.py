"""Model benchmark harness (T074).

Times a callable operation without loading real AI models (NFR-006):
callers inject lightweight stand-ins. Reports mean/p50 latency and
throughput so model/profile choices stay benchmark-driven.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelBenchResult:
    """Latency summary for one benchmarked operation."""

    operation: str
    model: str
    repeats: int
    mean_seconds: float
    p50_seconds: float
    min_seconds: float
    max_seconds: float
    throughput_per_sec: float


def benchmark_operation(
    operation: str,
    model: str,
    fn: Callable[[], int],
    *,
    repeats: int = 3,
) -> ModelBenchResult:
    """Run ``fn`` ``repeats`` times; ``fn`` returns units produced."""
    if repeats < 1:
        raise ValueError(f"repeats must be >= 1: {repeats}")
    samples: list[float] = []
    units = 0
    for _ in range(repeats):
        started = time.perf_counter()
        units = fn()
        samples.append(time.perf_counter() - started)
    mean = statistics.fmean(samples)
    ordered = sorted(samples)
    p50 = ordered[len(ordered) // 2]
    return ModelBenchResult(
        operation=operation,
        model=model,
        repeats=repeats,
        mean_seconds=mean,
        p50_seconds=p50,
        min_seconds=min(samples),
        max_seconds=max(samples),
        throughput_per_sec=(units / mean) if mean > 0 else 0.0,
    )
