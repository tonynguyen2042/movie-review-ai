"""The render stage and the timeline editor must read the manifest that is written.

T116 regression. `rendering/manifest.py` wrote the manifest flat —
`{"segments": [...], "total_seconds": ..., "source_seconds": ...}` — while the
render stage read `manifest_data["manifest"]`, the envelope that belongs to
the cache payload. The render stage therefore raised `KeyError: 'manifest'`
on every real run and had never once succeeded.

These tests write a manifest the way the pipeline writes it and read it back
the way the pipeline reads it, so the two shapes cannot drift again.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.artifacts import manager as artifacts
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus, ReviewParagraph
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.rendering.clips import SelectedClip
from movie_review.rendering.manifest import (
    ManifestError,
    assemble_manifest,
    read_manifest,
    read_manifest_document,
)
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.ui.timeline_editor import VisualTimelineEditor


def _paragraph(paragraph_id: str) -> ReviewParagraph:
    return ReviewParagraph(
        id=paragraph_id, text="Narration.", target_seconds=12, claims=[], visual_intent="s"
    )


def _clip(paragraph_id: str, start: float, end: float) -> SelectedClip:
    return SelectedClip(paragraph_id, "scene_000001", start, end)


@dataclass
class Harness:
    conn: sqlite3.Connection
    ctx: StageContext


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


def _write_a_real_manifest(tmp_path: Path) -> Path:
    """Assemble a manifest the way the pipeline does, and return its path."""
    harness = _harness(tmp_path)
    result = assemble_manifest(
        [_paragraph("p1")],
        {"p1": _clip("p1", 0.0, 5.0)},
        {"p1": 10.0},
        100.0,
        harness.ctx,
    )
    return result.manifest_path


def test_the_manifest_file_holds_the_manifest_itself(tmp_path: Path) -> None:
    """The file shape is the manifest, not the cache payload's envelope."""
    manifest_path = _write_a_real_manifest(tmp_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "segments" in document
    assert "manifest" not in document


def test_the_render_stage_reads_the_manifest_that_was_written(tmp_path: Path) -> None:
    """Regression: the render stage raised KeyError('manifest') on every run."""
    manifest_path = _write_a_real_manifest(tmp_path)
    manifest = read_manifest(manifest_path)
    assert len(manifest.segments) == 1
    assert manifest.segments[0].paragraph_id == "p1"
    assert manifest.total_seconds == 10.0


def test_the_timeline_editor_renders_a_real_manifest(tmp_path: Path) -> None:
    """Regression: the editor rendered zero clips against a real manifest."""
    _write_a_real_manifest(tmp_path)
    editor = VisualTimelineEditor(tmp_path / "jobs", "job_1")
    data = editor.load()
    assert data["clip_count"] == 1
    assert data["total_duration"] == 10.0
    video_track = next(t for t in data["tracks"] if t["id"] == "video")
    assert video_track["clips"][0]["paragraph_id"] == "p1"


def test_a_nested_envelope_is_still_readable(tmp_path: Path) -> None:
    """A hand-written manifest may carry the envelope; it must still load."""
    job_dir = tmp_path / "jobs" / "job_1" / "render"
    job_dir.mkdir(parents=True)
    path = job_dir / "render-manifest.json"
    artifacts.write_json(
        path,
        {
            "manifest": {
                "segments": [
                    {
                        "paragraph_id": "p1",
                        "scene_id": "s1",
                        "clip_start": 0.0,
                        "clip_end": 5.0,
                        "start": 0.0,
                        "duration": 10.0,
                    }
                ],
                "total_seconds": 10.0,
                "source_seconds": 5.0,
            }
        },
    )
    document = read_manifest_document(path)
    assert document["total_seconds"] == 10.0
    assert read_manifest(path).total_seconds == 10.0


def test_an_invalid_manifest_is_reported_as_a_manifest_error(tmp_path: Path) -> None:
    """A corrupt manifest must fail as a manifest error, not as a KeyError."""
    job_dir = tmp_path / "jobs" / "job_1" / "render"
    job_dir.mkdir(parents=True)
    path = job_dir / "render-manifest.json"
    artifacts.write_json(path, {"segments": "not a list"})
    with pytest.raises(ManifestError, match="Invalid render manifest"):
        read_manifest(path)
