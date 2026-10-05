"""Clip selection: planned scenes → exact ranges (T057, spec section 38).

Cuts each paragraph's top-ranked scene to a source-footage window honoring
the configured per-clip limits. Total-ratio limits apply at manifest level
(T058); this stage only bounds individual clips.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from movie_review.domain import Event, ReviewParagraph, Scene
from movie_review.rendering.planner import paragraph_claim_refs
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)


class ClipSelectionError(Exception):
    """Clip selection failed in a classified way."""


@dataclass(frozen=True)
class SelectedClip:
    """One paragraph's exact source range (slots for T058 manifest)."""

    paragraph_id: str
    scene_id: str
    start: float
    end: float

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ClipSelectionError(f"Empty clip range for {self.paragraph_id}")

    @property
    def duration(self) -> float:
        """Clip length in seconds."""
        return self.end - self.start


def cut_window(
    scene: Scene, center: float, length: float, max_clip_seconds: float
) -> tuple[float, float]:
    """Clamp a centered window to scene bounds and the per-clip limit."""
    if max_clip_seconds <= 0:
        raise ClipSelectionError(f"Invalid clip limit: {max_clip_seconds}")
    span = min(length, max_clip_seconds, scene.end - scene.start)
    if span <= 0:
        raise ClipSelectionError(f"Scene {scene.scene_id} has no duration")
    half = span / 2
    start = min(max(center - half, scene.start), scene.end - span)
    return (start, start + span)


def select_clips(
    paragraphs: list[ReviewParagraph],
    plan_scenes: dict[str, str],
    scenes: list[Scene],
    events: list[Event],
    max_clip_seconds: float = 8.0,
    preferred_seconds: float = 3.0,
) -> list[SelectedClip]:
    """Cut each paragraph's planned scene around its evidence (or middle).

    Args:
        paragraphs: narration paragraphs in order.
        plan_scenes: paragraph ID → top-ranked scene ID from T056.
        scenes: scene timeline for bounds.
        events: for centering event-linked clips.
    """
    by_scene = {scene.scene_id: scene for scene in scenes}
    by_event = {event.id: event for event in events}
    selected: list[SelectedClip] = []
    for paragraph in paragraphs:
        scene_id = plan_scenes.get(paragraph.id)
        if scene_id is None:
            raise ClipSelectionError(f"No planned scene for {paragraph.id}")
        scene = by_scene.get(scene_id)
        if scene is None:
            raise ClipSelectionError(f"Unknown scene {scene_id} for {paragraph.id}")
        center = (scene.start + scene.end) / 2
        for ref in paragraph_claim_refs(paragraph):
            event = by_event.get(ref)
            if event is not None and scene.start <= event.timestamp < scene.end:
                center = event.timestamp
                break
        start, end = cut_window(scene, center, preferred_seconds, max_clip_seconds)
        selected.append(SelectedClip(paragraph.id, scene_id, start, end))
    with ulog.logging_context(stage="clip-select"):
        ulog.log_event(_logger, event="selection.completed", status="ok", clips=len(selected))
    return selected
