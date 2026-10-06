"""Pipeline stage benchmark (T075, NFR-004).

Times named stage callables end-to-end (with injected fakes in tests) and
reports per-stage durations plus the total, supporting the balanced-mode
``< 8h for a 2h movie`` target as measurement rather than assertion.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageTiming:
    """Duration of one pipeline stage."""

    stage: str
    seconds: float


@dataclass(frozen=True)
class PipelineBenchReport:
    """Per-stage timings plus total wall time."""

    stages: list[StageTiming] = field(default_factory=list)

    @property
    def total_seconds(self) -> float:
        return sum(item.seconds for item in self.stages)

    def slowest(self) -> StageTiming | None:
        return max(self.stages, key=lambda item: item.seconds, default=None)


def benchmark_pipeline(stages: Mapping[str, Callable[[], object]]) -> PipelineBenchReport:
    """Run each stage callable once and time it."""
    if not stages:
        raise ValueError("at least one stage is required")
    timings: list[StageTiming] = []
    for name, fn in stages.items():
        started = time.perf_counter()
        fn()
        timings.append(StageTiming(stage=name, seconds=time.perf_counter() - started))
    return PipelineBenchReport(stages=timings)
