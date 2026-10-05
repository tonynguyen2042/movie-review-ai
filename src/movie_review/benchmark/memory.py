"""Memory benchmark (T076, NFR-005).

Measures peak allocation of an operation with :mod:`tracemalloc` (stdlib,
no model downloads) so sequential-residency decisions stay measurement
driven on the 128 GB Apple Silicon target.
"""

from __future__ import annotations

import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryBenchResult:
    """Peak-memory summary for one operation."""

    operation: str
    peak_bytes: int
    current_bytes: int
    peak_mb: float


def benchmark_memory(operation: str, fn: Callable[[], Any]) -> MemoryBenchResult:
    """Run ``fn`` under tracemalloc and report peak bytes."""
    tracemalloc.start()
    try:
        fn()
        _, peak = tracemalloc.get_traced_memory()
        current, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return MemoryBenchResult(
        operation=operation,
        peak_bytes=peak,
        current_bytes=current,
        peak_mb=peak / (1024 * 1024),
    )
