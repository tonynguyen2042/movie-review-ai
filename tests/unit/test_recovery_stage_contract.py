"""Invariant: recovery resume targets must be real pipeline stages.

``resume_job`` hands ``recovery_plan(...).resume_stage`` straight to
``run_pipeline`` as the start stage. If the two disagree on stage names the
job either raises or silently skips stages that never ran.

The recovery table and ``STAGE_SEQUENCE`` live in different modules and were
never cross-checked, so this pins them together.
"""

import pytest

from movie_review.domain import JobStatus
from movie_review.jobs.recovery import _RESUME_STAGE
from movie_review.pipeline.orchestrator import STAGE_SEQUENCE

STAGES = [name for name, _ in STAGE_SEQUENCE]
#: terminal markers that are not pipeline stages
TERMINAL = {"done", "manual"}

#: stages that carry no dedicated JobStatus, so they are covered by the
#: window between the neighbouring statuses. A status that precedes them must
#: not resume past them.
UNTRACKED_STAGES = ("locations", "arcs", "themes", "twists")


@pytest.mark.parametrize("target", sorted(set(_RESUME_STAGE.values())))
def test_every_resume_target_is_a_real_stage(target: str) -> None:
    """A resume target must be a stage in STAGE_SEQUENCE (or a terminal marker)."""
    assert target in STAGES or target in TERMINAL, (
        f"{target!r} is not a pipeline stage; resume would fail or skip work"
    )


@pytest.mark.parametrize("status", [s for s in JobStatus if s is not JobStatus.FAILED])
def test_every_status_has_a_resume_target(status: JobStatus) -> None:
    """No status may fall through to RecoveryMappingError in normal operation."""
    assert status in _RESUME_STAGE, f"{status} has no resume target"


def test_resume_never_overrides_its_status() -> None:
    """Each resume target must not sit behind the stage that set the status.

    Resuming at or after the recorded progress is safe -- stages are
    idempotent, so re-running the recorded stage is harmless. Falling behind
    would silently drop work the status says was already done.
    """
    # the stage that produces each status, in pipeline order
    completed_by = {
        JobStatus.CREATED: None,
        JobStatus.INGESTING: None,
        JobStatus.MEDIA_READY: "ingest",
        JobStatus.SCENES_READY: "scenes",
        JobStatus.TRANSCRIPT_READY: "transcript",
        JobStatus.VISUAL_ANALYSIS_READY: "vision",
        JobStatus.CHARACTERS_READY: "characters",
        JobStatus.EVENTS_READY: "events",
        JobStatus.STORY_READY: "story",
        JobStatus.REVIEW_PLAN_READY: "review",
        JobStatus.SCRIPT_READY: "review",
        JobStatus.SCRIPT_VERIFIED: "review",
        JobStatus.AUDIO_READY: "tts-reconcile",
        JobStatus.EDIT_PLAN_READY: "render-manifest",
        JobStatus.RENDERED: "render",
        JobStatus.QUALITY_CHECKED: "quality",
    }

    for status, completed in completed_by.items():
        target = _RESUME_STAGE.get(status)
        if target is None or target in TERMINAL or completed is None:
            continue
        assert STAGES.index(target) >= STAGES.index(completed), (
            f"{status.value} already completed {completed!r} but resumes behind it at {target!r}"
        )


def test_untracked_stages_are_not_skipped() -> None:
    """locations/arcs/themes/twists have no status of their own.

    The status that precedes each window must resume at or before the first
    untracked stage in that window, or resume would skip them permanently.
    """
    assert "locations" in STAGES and "arcs" in STAGES

    # CHARACTERS_READY means characters finished; locations has not run
    assert STAGES.index(_RESUME_STAGE[JobStatus.CHARACTERS_READY]) <= STAGES.index("locations")
    # EVENTS_READY means events finished; arcs has not run
    assert STAGES.index(_RESUME_STAGE[JobStatus.EVENTS_READY]) <= STAGES.index("arcs")


def test_tts_resume_uses_a_real_tts_stage() -> None:
    """Regression: the table said 'tts', which is not a stage name.

    SCRIPT_READY now resumes at review-translate, which sits between writing the
    script and speaking it. What matters is that the resume point is a real stage
    and that no audio stage is skipped on the way to TTS.
    """
    for status in (JobStatus.SCRIPT_READY, JobStatus.SCRIPT_VERIFIED):
        target = _RESUME_STAGE[status]
        assert target in STAGES, f"{status.value} resumes at unregistered {target!r}"

    assert _RESUME_STAGE[JobStatus.SCRIPT_READY] == "review-translate"
    assert _RESUME_STAGE[JobStatus.SCRIPT_VERIFIED] == "tts-chunks"


def test_script_ready_resume_does_not_skip_translation() -> None:
    """Resuming straight into TTS would speak the source language.

    The whole point of the target language is lost if a job interrupted after
    writing the script is resumed with translation bypassed.
    """
    target = _RESUME_STAGE[JobStatus.SCRIPT_READY]
    assert STAGES.index("review") < STAGES.index(target) < STAGES.index("tts-chunks")
