"""Timeline consistency metric (T065, spec gate >= 95).

Share of events whose timestamps fall inside a detected scene span, as a
0-100 score. Vacuously 100 when no events exist.
"""

from __future__ import annotations

from movie_review.domain import Event, QualityMetric, Scene


def timeline_consistency(events: list[Event], scenes: list[Scene]) -> QualityMetric:
    """Score event-to-scene timeline alignment."""
    if not events:
        return QualityMetric(name="timeline_consistency", score=100.0, detail="no events")
    uncovered = [
        event.id
        for event in events
        if not any(scene.start <= event.timestamp < scene.end for scene in scenes)
    ]
    score = (len(events) - len(uncovered)) / len(events) * 100.0
    return QualityMetric(
        name="timeline_consistency",
        score=score,
        detail=f"{len(events) - len(uncovered)}/{len(events)} events inside scenes"
        + (f"; uncovered: {uncovered}" if uncovered else ""),
    )
