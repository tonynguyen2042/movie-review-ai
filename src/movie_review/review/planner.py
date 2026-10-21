"""Deterministic review planner (T041, spec sections 27-28).

Planning is evidence arithmetic, not generation (P2): section time follows
the default structure scaled to the style target, and events are assigned by
type rules plus importance. The planner redistributes time but never invents
content; empty inputs yield structured time with empty references.
"""

from __future__ import annotations

from movie_review.domain import Event, EventType, OutlineSection, ReviewPlan
from movie_review.review.styles import StyleProfile

# (section type, fraction of total, purpose) — fractions sum to 1.0.
_SECTIONS: tuple[tuple[str, float, str], ...] = (
    ("hook", 40 / 1200, "open with the central mystery"),
    ("premise", 80 / 1200, "establish premise and stakes"),
    ("characters", 150 / 1200, "introduce major characters"),
    ("setup", 210 / 1200, "cover the setup"),
    ("conflict", 270 / 1200, "develop the main conflict"),
    ("revelations", 210 / 1200, "explain major revelations"),
    ("climax", 150 / 1200, "retell the climax"),
    ("ending", 90 / 1200, "ending plus analysis"),
)

_SECTION_TYPES: dict[str, set[EventType]] = {
    "premise": {EventType.INTRODUCTION, EventType.MEETING},
    "conflict": {EventType.CONFLICT, EventType.CLIMAX, EventType.BETRAYAL, EventType.ACTION},
    "revelations": {EventType.REVELATION, EventType.DISCOVERY, EventType.DECEPTION},
    "climax": {EventType.CLIMAX},
    "ending": {EventType.RESOLUTION},
}

_MAX_REFS = 4


def _top(events: list[Event], count: int) -> list[Event]:
    return sorted(events, key=lambda e: (-e.importance, e.timestamp))[:count]


def _of_types(events: list[Event], types: set[EventType], count: int) -> list[Event]:
    return _top([e for e in events if e.type in types], count)


def _buckets(events: list[Event]) -> dict[str, list[Event]]:
    """The events each section may draw on, ranked once.

    The planner sorted the event list seven independent times -- once for
    the ranking and once for each section type -- and each sort walked
    every event. The list is sorted once here and every section takes
    what it needs from the same ranked order.
    """
    ranked = sorted(events, key=lambda e: (-e.importance, e.timestamp))
    by_type: dict[EventType, list[Event]] = {}
    for event in ranked:
        by_type.setdefault(event.type, []).append(event)

    # How many references each section may cite.
    limits = {"climax": 1, "ending": 2}

    buckets: dict[str, list[Event]] = {"hook": ranked[:1]}
    for name, types in _SECTION_TYPES.items():
        limit = limits.get(name, _MAX_REFS)
        picked: list[Event] = []
        for event_type in types:
            for event in by_type.get(event_type, []):
                if len(picked) >= limit:
                    break
                picked.append(event)
            if len(picked) >= limit:
                break
        buckets[name] = picked
    return buckets


def plan_review(
    events: list[Event], style: StyleProfile, target_seconds: float | None = None
) -> ReviewPlan:
    """Build a timed outline referencing the strongest evidence.

    The total is whole seconds: the sections are measured in seconds, and a
    fractional total would leave the last section a fraction long.
    """
    total = int(style.target_duration_seconds if target_seconds is None else target_seconds)
    if total <= 0:
        raise ValueError(f"Target duration must be positive: {total}")
    ranked = _top(events, len(events))
    hook_max = int(style.hook.get("max_seconds", 45)) if isinstance(style.hook, dict) else 45

    buckets = _buckets(events)
    picked: dict[str, list[Event]] = {
        "hook": buckets["hook"],
        "premise": buckets["premise"],
        "characters": sorted(events, key=lambda e: (-len(e.characters), -e.importance))[:_MAX_REFS],
        "setup": sorted(events, key=lambda e: e.timestamp)[:_MAX_REFS],
        "conflict": buckets["conflict"],
        "revelations": buckets["revelations"],
        "climax": buckets["climax"] or ranked[:1],
        "ending": buckets["ending"],
    }

    sections: list[OutlineSection] = []
    allotted = 0
    templates = list(_SECTIONS)
    for position, (section_type, fraction, purpose) in enumerate(templates):
        seconds = max(1, round(fraction * total))
        if section_type == "hook":
            seconds = max(1, min(seconds, hook_max))
        if position == len(templates) - 1:
            seconds = max(1, total - allotted)
        allotted += seconds
        sections.append(
            OutlineSection(
                id=f"section_{position + 1:02d}",
                type=section_type,
                target_seconds=seconds,
                event_ids=[event.id for event in picked[section_type]],
                purpose=purpose,
            )
        )
    return ReviewPlan(sections=sections, total_seconds=sum(s.target_seconds for s in sections))
