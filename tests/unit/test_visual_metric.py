"""T067 acceptance: plan-to-render alignment scoring."""

from movie_review.domain import ManifestSegment, PlannedClip, RenderManifest, VisualPlan
from movie_review.quality.visual import visual_alignment


def _plan() -> VisualPlan:
    return VisualPlan(
        paragraph_clips=[
            PlannedClip(paragraph_id="p1", scene_id="s1", priority=1, reason="direct"),
            PlannedClip(paragraph_id="p1", scene_id="s2", priority=2, reason="reaction"),
            PlannedClip(paragraph_id="p2", scene_id="s2", priority=1, reason="direct"),
        ]
    )


def _manifest(*scenes: tuple[str, str]) -> RenderManifest:
    segments = [
        ManifestSegment(
            paragraph_id=paragraph,
            start=float(i * 10),
            duration=10.0,
            scene_id=scene,
            clip_start=0.0,
            clip_end=3.0,
        )
        for i, (paragraph, scene) in enumerate(scenes)
    ]
    return RenderManifest(
        segments=segments, total_seconds=10.0 * len(segments), source_seconds=3.0 * len(segments)
    )


def test_aligned_scores_100() -> None:
    metric = visual_alignment(_plan(), _manifest(("p1", "s1"), ("p2", "s2")))
    assert metric.name == "visual_alignment"
    assert metric.score == 100.0


def test_misaligned_penalized() -> None:
    metric = visual_alignment(_plan(), _manifest(("p1", "s9"), ("p2", "s2")))
    assert metric.score == 50.0
    assert "p1" in metric.detail


def test_missing_plan_entry_misaligned() -> None:
    metric = visual_alignment(
        _plan(),
        _manifest(
            ("p3", "s1"),
        ),
    )
    assert metric.score == 0.0


def test_empty_manifest_vacuous() -> None:
    manifest = RenderManifest.model_construct(segments=[], total_seconds=0.0, source_seconds=0.0)
    assert visual_alignment(_plan(), manifest).score == 100.0
