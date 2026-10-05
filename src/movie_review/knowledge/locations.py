"""Location extraction from scene analyses (T030).

Canonicalizes VLM location strings (case/whitespace) into stable ``loc_NNN``
records with first/last seen timestamps. Empty locations are skipped; no
location is invented.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from movie_review.asr.normalize import normalize_text
from movie_review.domain import Location, Scene, SceneAnalysis
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)


@dataclass
class _Accumulated:
    name: str
    first: float
    last: float
    scenes: int = 1


def extract_locations(
    analyses: list[SceneAnalysis], scene_spans: dict[str, tuple[float, float]]
) -> list[Location]:
    """Merge per-scene locations into canonical records in first-seen order."""
    seen: dict[str, _Accumulated] = {}
    for analysis in analyses:
        span = scene_spans.get(analysis.scene_id)
        if span is None:
            continue
        name = normalize_text(analysis.location)
        if not name:
            continue
        key = name.lower()
        record = seen.get(key)
        if record is None:
            seen[key] = _Accumulated(name=name, first=span[0], last=span[1])
        else:
            record.first = min(record.first, span[0])
            record.last = max(record.last, span[1])
            record.scenes += 1

    ordered = sorted(seen.values(), key=lambda record: (record.first, record.name))
    locations = []
    for index, record in enumerate(ordered, start=1):
        locations.append(
            Location(
                id=f"loc_{index:03d}",
                name=record.name,
                first_seen=record.first,
                last_seen=record.last,
                confidence=min(0.6 + 0.1 * record.scenes, 0.9),
            )
        )
    with ulog.logging_context(stage="knowledge"):
        ulog.log_event(_logger, event="locations.extracted", status="ok", locations=len(locations))
    return locations


def scene_locations(scenes: list[Scene]) -> dict[str, tuple[float, float]]:
    """Build scene spans for extraction from persisted scenes."""
    return {scene.scene_id: (scene.start, scene.end) for scene in scenes}
