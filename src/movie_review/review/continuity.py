"""Continuity checking over events and scenes (T048, spec section 34).

Deterministic rules on available data: post-death activity (with the
flashback exemption) and dangling scene references. Location, ownership,
and relationship-state checks need per-frame tracking and arrive later.
"""

from __future__ import annotations

from dataclasses import dataclass

from movie_review.domain import Event, EventType, Scene

_EXEMPT_TYPES = frozenset({EventType.FLASHBACK, EventType.FLASH_FORWARD})


@dataclass(frozen=True)
class ContinuityIssue:
    """One continuity violation with its evidence."""

    kind: str
    subject: str
    detail: str


def check_continuity(events: list[Event], scenes: list[Scene]) -> list[ContinuityIssue]:
    """Check death consistency and scene reference integrity, in order."""
    issues: list[ContinuityIssue] = []
    ordered = sorted(events, key=lambda event: (event.timestamp, event.id))
    scene_ids = {scene.scene_id for scene in scenes}

    deaths: dict[str, Event] = {}
    for event in ordered:
        if event.type is EventType.DEATH:
            for character_id in event.characters:
                deaths.setdefault(character_id, event)

    for event in ordered:
        if event.type in _EXEMPT_TYPES:
            continue
        for character_id in event.characters:
            death = deaths.get(character_id)
            if death is not None and event.timestamp > death.timestamp and event.id != death.id:
                issues.append(
                    ContinuityIssue(
                        kind="character-active-after-death",
                        subject=character_id,
                        detail=f"{event.id} @ {event.timestamp} after death in {death.id}",
                    )
                )
        for ref in event.evidence:
            if ref.startswith("scene_") and ref not in scene_ids:
                issues.append(
                    ContinuityIssue(
                        kind="dangling-scene-ref",
                        subject=event.id,
                        detail=f"unknown scene {ref}",
                    )
                )
    return issues
