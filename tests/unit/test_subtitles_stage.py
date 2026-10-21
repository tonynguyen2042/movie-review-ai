"""The subtitle sidecar must be produced from the real narration timing.

T143. `rendering/subtitles.py` was complete and tested, and nothing called
it. `review.srt` -- a required output of v1.0 -- was never produced; the
renderer only copied a sidecar if it happened to exist.

README section 47 also forbids estimating the subtitle duration from the
word count, so the cues are built from the manifest's real segment timings.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from movie_review.artifacts import manager as artifacts
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import (
    Job,
    ManifestSegment,
    RenderManifest,
    ReviewParagraph,
    ReviewScript,
    ReviewSection,
)
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.pipeline.subtitles import SubtitleStageError, write_subtitles
from movie_review.rendering.subtitles import parse_srt
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _ctx__subtitles_stage(tmp_path: Path) -> tuple[StageContext, sqlite3.Connection]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
    )
    return ctx, conn


def _manifest_path(tmp_path: Path, durations: list[float], ids: list[str] | None = None) -> Path:
    path = tmp_path / "jobs" / "job_1" / "render" / "render-manifest.json"
    segments = []
    start = 0.0
    for index, duration in enumerate(durations, start=1):
        segments.append(
            ManifestSegment(
                paragraph_id=(ids[index - 1] if ids else f"p{index}"),
                start=start,
                duration=duration,
                scene_id="scene_000001",
                clip_start=0.0,
                clip_end=duration,
            )
        )
        start += duration
    manifest = RenderManifest(segments=segments, total_seconds=start, source_seconds=sum(durations))
    artifacts.write_json(path, manifest.model_dump(mode="json"))
    return path


def _script__subtitles_stage() -> ReviewScript:
    return ReviewScript(
        sections=[
            ReviewSection(
                id="sec_001",
                type="hook",
                paragraphs=[
                    ReviewParagraph(
                        id="p1",
                        text="The hero walks into the room and looks around.",
                        target_seconds=10,
                        claims=[],
                        visual_intent="s",
                    ),
                    ReviewParagraph(
                        id="p2",
                        text="And then everything changes.",
                        target_seconds=8,
                        claims=[],
                        visual_intent="s",
                    ),
                ],
            )
        ]
    )


def test_the_sidecar_is_written(tmp_path: Path) -> None:
    """`review.srt` is a required output of v1.0 and was never produced."""
    ctx, conn = _ctx__subtitles_stage(tmp_path)
    try:
        manifest_path = _manifest_path(tmp_path, [10.0, 8.0])
        result = write_subtitles(manifest_path, _script__subtitles_stage(), ctx)

        assert result.srt_path.is_file()
        assert result.srt_path.name == "review.srt"
        assert result.cue_count > 0
        assert repo.get_artifact(conn, "job_1-subtitles") is not None
    finally:
        conn.close()


def test_the_cues_follow_the_manifest_timing(tmp_path: Path) -> None:
    """The timing comes from the narration, not from the word count."""
    ctx, conn = _ctx__subtitles_stage(tmp_path)
    try:
        manifest_path = _manifest_path(tmp_path, [10.0, 8.0])
        result = write_subtitles(manifest_path, _script__subtitles_stage(), ctx)

        cues = parse_srt(result.srt_path.read_text(encoding="utf-8"))
        assert cues
        # The first paragraph spans the first ten seconds.
        first = [cue for cue in cues if cue.start < 10.0]
        assert first
        assert all(cue.end <= 10.0 for cue in first)
        # The last cue ends when the narration does.
        assert cues[-1].end == pytest.approx(18.0)
    finally:
        conn.close()


def test_a_missing_manifest_is_reported(tmp_path: Path) -> None:
    """A missing manifest is a classified failure, not a crash."""
    ctx, conn = _ctx__subtitles_stage(tmp_path)
    try:
        with pytest.raises(SubtitleStageError, match="No render manifest"):
            write_subtitles(
                tmp_path / "jobs" / "job_1" / "render" / "render-manifest.json",
                _script__subtitles_stage(),
                ctx,
            )
    finally:
        conn.close()


def test_a_manifest_with_no_matching_text_is_reported(tmp_path: Path) -> None:
    """A manifest whose paragraphs the script does not have has nothing to say."""
    ctx, conn = _ctx__subtitles_stage(tmp_path)
    try:
        # The manifest names p9; the script does not have it.
        manifest_path = _manifest_path(tmp_path, [10.0], ids=["p9"])
        with pytest.raises(SubtitleStageError, match="no subtitle text"):
            write_subtitles(manifest_path, _script__subtitles_stage(), ctx)
    finally:
        conn.close()


def test_the_stage_is_in_the_pipeline() -> None:
    """A stage nobody can reach is not a stage."""
    from movie_review.pipeline.orchestrator import STAGE_SEQUENCE

    order = [name for name, _ in STAGE_SEQUENCE]
    assert "subtitles" in order
    # The sidecar has to exist before the renderer copies it.
    assert order.index("subtitles") < order.index("render")
