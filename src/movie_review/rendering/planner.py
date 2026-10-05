"""Visual planner: narration paragraphs → evidence scenes (T056, spec 36-37).

Priority order: direct evidence clips, character reaction shots,
location/context matches, object matches, then an establishing fallback.
Exact time ranges arrive with clip selection (T057); this stage only ranks
scenes per paragraph.
"""

from __future__ import annotations

import logging

from movie_review.domain import (
    Event,
    PlannedClip,
    ReviewParagraph,
    ReviewScript,
    Scene,
    SceneAnalysis,
    VisualPlan,
)
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)


def _scene_spans(scenes: list[Scene]) -> dict[str, Scene]:
    return {scene.scene_id: scene for scene in scenes}


def _events_by_id(events: list[Event]) -> dict[str, Event]:
    return {event.id: event for event in events}


def plan_visuals(
    script: ReviewScript,
    scenes: list[Scene],
    analyses: dict[str, SceneAnalysis],
    events: list[Event],
) -> VisualPlan:
    """Map every paragraph to ranked scene candidates."""
    by_id = _events_by_id(events)
    spans = _scene_spans(scenes)
    clips: list[PlannedClip] = []
    for section in script.sections:
        for paragraph in section.paragraphs:
            ranked = _rank_scenes(paragraph_claim_refs(paragraph), spans, analyses, by_id)
            for priority, (scene_id, reason) in enumerate(ranked, start=1):
                clips.append(
                    PlannedClip(
                        paragraph_id=paragraph.id,
                        scene_id=scene_id,
                        priority=priority,
                        reason=reason,
                    )
                )
    with ulog.logging_context(stage="visual-plan"):
        ulog.log_event(_logger, event="planning.completed", status="ok", clips=len(clips))
    return VisualPlan(paragraph_clips=clips)


def paragraph_claim_refs(paragraph: ReviewParagraph) -> list[str]:
    """Evidence IDs cited by a paragraph's claims, deduplicated in order."""
    refs: list[str] = []
    for claim in paragraph.claims:
        for ref in claim.evidence:
            if ref not in refs:
                refs.append(ref)
    return refs


def _rank_scenes(
    refs: list[str],
    spans: dict[str, Scene],
    analyses: dict[str, SceneAnalysis],
    by_id: dict[str, Event],
) -> list[tuple[str, str]]:
    ranked: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(scene_id: str, reason: str) -> None:
        if scene_id in spans and scene_id not in seen:
            seen.add(scene_id)
            ranked.append((scene_id, reason))

    # 1. Direct evidence: cited scenes and scenes holding cited events.
    for ref in refs:
        if ref in spans:
            _add(ref, "direct evidence clip")
        elif ref in by_id:
            event = by_id[ref]
            for scene_id, scene in spans.items():
                if scene.start <= event.timestamp < scene.end:
                    _add(scene_id, f"event {ref} occurs here")
    # 2. Character reaction: scenes listing characters from cited events.
    wanted: set[str] = set()
    for ref in refs:
        if ref in by_id:
            wanted.update(by_id[ref].characters)
    if wanted:
        for scene_id, analysis in analyses.items():
            if wanted & set(analysis.characters):
                _add(scene_id, "character reaction")
    # 3-4. Location/context and object matches from ranked scenes.
    anchors = [scene_id for scene_id, _ in ranked]
    anchor_locations = {
        analyses[scene_id].location for scene_id in anchors if scene_id in analyses
    } - {""}
    anchor_objects: set[str] = set()
    for scene_id in anchors:
        if scene_id in analyses:
            anchor_objects.update(analyses[scene_id].objects)
    for scene_id, analysis in analyses.items():
        if analysis.location and analysis.location in anchor_locations:
            _add(scene_id, "location context")
    for scene_id, analysis in analyses.items():
        if anchor_objects & set(analysis.objects):
            _add(scene_id, "relevant object")
    # 5. Establishing fallback: opening scene.
    if spans and not ranked:
        first = min(spans.values(), key=lambda s: s.start)
        _add(first.scene_id, "establishing fallback")
    return ranked
