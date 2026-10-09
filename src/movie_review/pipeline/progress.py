"""Incremental progress inside a stage (T101).

Stage boundaries were the only progress signal: ``on_progress`` fired before a
stage started and after it finished. A bar built on that alone sits at 0% for the
whole of a nine-minute transcription, which is the "is it hung?" problem the
stage heartbeat was meant to solve.

So stages that iterate over a known number of items report each step here. The
loop count is known up front -- ``len(scenes)`` for visual analysis, and the sum
of the per-scene bucket counts for frame sampling -- so this carries a real
fraction rather than a spinner.

A stage that cannot divide its work (one ASR call, one ffmpeg render) reports
nothing and leaves the heartbeat to prove liveness. Inventing a percentage there
would be a lie that moves on its own.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkProgress:
    """One step of in-stage work.

    Args:
        done: completed items, from 0 to ``total``.
        total: total items, or 0 when the count is genuinely unknown.
        label: short human description, e.g. ``scene 12/48``.

    A ``total`` of 0 is legal and means "unknown" -- callers must not divide by
    it. Keeping that case in the type beats raising, because a stage that
    discovers its total late should report partial progress rather than abort.
    """

    done: int
    total: int
    label: str = ""

    def __post_init__(self) -> None:
        if self.done < 0:
            raise ValueError(f"done must be >= 0, got {self.done}")
        if self.total < 0:
            raise ValueError(f"total must be >= 0, got {self.total}")
        if self.total and self.done > self.total:
            raise ValueError(f"done ({self.done}) exceeds total ({self.total})")

    @property
    def fraction(self) -> float:
        """Completion in [0, 1]; 0.0 when the total is unknown."""
        if not self.total:
            return 0.0
        return min(1.0, self.done / self.total)

    @property
    def percent(self) -> int:
        """Completion as a whole percentage in [0, 100]."""
        return int(self.fraction * 100)


#: Callback a stage uses to publish in-stage progress.
ProgressReporter = Callable[[WorkProgress], None]
