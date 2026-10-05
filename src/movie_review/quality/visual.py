"""Visual alignment metric (T067).

Share of render segments using their paragraph's top-planned scene, as a
0-100 score. Vacuously 100 when the manifest is empty.
"""

from __future__ import annotations

from movie_review.domain import QualityMetric, RenderManifest, VisualPlan


def visual_alignment(plan: VisualPlan, manifest: RenderManifest) -> QualityMetric:
    """Score plan-to-render scene agreement."""
    top: dict[str, tuple[int, str]] = {}
    for clip in plan.paragraph_clips:
        if clip.paragraph_id not in top or clip.priority < top[clip.paragraph_id][0]:
            top[clip.paragraph_id] = (clip.priority, clip.scene_id)
    segments = manifest.segments
    if not segments:
        return QualityMetric(name="visual_alignment", score=100.0, detail="no segments")
    misaligned = [
        segment.paragraph_id
        for segment in segments
        if segment.paragraph_id not in top or top[segment.paragraph_id][1] != segment.scene_id
    ]
    score = (len(segments) - len(misaligned)) / len(segments) * 100.0
    return QualityMetric(
        name="visual_alignment",
        score=score,
        detail=f"{len(segments) - len(misaligned)}/{len(segments)} segments aligned"
        + (f"; misaligned: {misaligned}" if misaligned else ""),
    )
