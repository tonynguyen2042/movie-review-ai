"""T058 acceptance: timeline assembly with enforced source limits."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus, ReviewParagraph
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.rendering.clips import SelectedClip
from movie_review.rendering.manifest import (
    ManifestError,
    ManifestResult,
    assemble_manifest,
    build_manifest,
)
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _paragraph(paragraph_id: str) -> ReviewParagraph:
    return ReviewParagraph(
        id=paragraph_id, text="Narration.", target_seconds=12, claims=[], visual_intent="s"
    )


def _clip(paragraph_id: str, start: float, end: float) -> SelectedClip:
    return SelectedClip(paragraph_id, "scene_000001", start, end)


def test_build_timeline_and_loop_flags() -> None:
    manifest = build_manifest(
        [_paragraph("p1"), _paragraph("p2")],
        {"p1": _clip("p1", 0.0, 5.0), "p2": _clip("p2", 0.0, 4.0)},
        {"p1": 10.0, "p2": 2.0},
        movie_duration_seconds=100.0,
        max_total_seconds=420.0,
        max_source_ratio=0.35,
    )
    assert [(s.start, s.duration) for s in manifest.segments] == [(0.0, 10.0), (10.0, 2.0)]
    assert [s.loop_clip for s in manifest.segments] == [True, False]
    assert manifest.total_seconds == 12.0
    assert manifest.source_seconds == pytest.approx(5.0 + 2.0)


def test_build_missing_inputs_rejected() -> None:
    with pytest.raises(ManifestError, match="No clip"):
        build_manifest([_paragraph("p1")], {}, {"p1": 5.0}, 100.0, 420.0, 0.35)
    with pytest.raises(ManifestError, match="No narration"):
        build_manifest([_paragraph("p1")], {"p1": _clip("p1", 0.0, 5.0)}, {}, 100.0, 420.0, 0.35)


def test_build_limits_enforced() -> None:
    paragraphs = [_paragraph("p1")]
    clips = {"p1": _clip("p1", 0.0, 5.0)}
    with pytest.raises(ManifestError, match="exceeds limit"):
        build_manifest(paragraphs, clips, {"p1": 10.0}, 100.0, 4.0, 0.35)
    with pytest.raises(ManifestError, match="ratio"):
        build_manifest(paragraphs, clips, {"p1": 10.0}, 100.0, 420.0, 0.01)


@dataclass
class Harness:
    conn: sqlite3.Connection
    ctx: StageContext

    def assemble(self) -> ManifestResult:
        return assemble_manifest(
            [_paragraph("p1")],
            {"p1": _clip("p1", 0.0, 5.0)},
            {"p1": 10.0},
            100.0,
            self.ctx,
        )


def _harness(tmp_path: Path) -> Harness:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
        JobStatus.VISUAL_ANALYSIS_READY,
        JobStatus.CHARACTERS_READY,
        JobStatus.EVENTS_READY,
        JobStatus.STORY_READY,
        JobStatus.REVIEW_PLAN_READY,
        JobStatus.SCRIPT_READY,
        JobStatus.SCRIPT_VERIFIED,
        JobStatus.AUDIO_READY,
    ):
        manager.transition("job_1", state)
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )
    return Harness(conn=conn, ctx=ctx)


def test_assemble_advances_lifecycle(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    result = harness.assemble()
    assert result.cache_hit is False
    assert result.manifest_path.is_file()
    assert harness.ctx.manager.get("job_1").status is JobStatus.EDIT_PLAN_READY
    assert repo.get_artifact(harness.conn, "job_1-render-manifest") is not None
    again = harness.assemble()
    assert again.cache_hit is True


def test_assemble_unknown_job(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.ctx.job_id = "job_2"
    with pytest.raises(ManifestError, match="Unknown job"):
        harness.assemble()
