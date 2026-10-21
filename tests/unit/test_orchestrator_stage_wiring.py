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
from movie_review.domain import (
    Job,
    JobStatus,
    Movie,
    MovieMetadata,
    ReviewParagraph,
    ReviewScript,
    ReviewSection,
    Scene,
)
from movie_review.jobs.manager import JobManager
from movie_review.jobs.recovery import recovery_plan
from movie_review.pipeline.context import StageContext
from movie_review.pipeline.orchestrator import (
    PipelineContext,
    _get_stage_function,
    review_target_words,
)
from movie_review.rendering.clips import SelectedClip
from movie_review.rendering.manifest import (
    ManifestError,
    assemble_manifest,
    read_manifest,
    read_manifest_document,
)
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.tts.chunks import plan_chunks
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


# ---------------------------------------------------------------------------
# The render manifest must be timed by the narration that was synthesized
# ---------------------------------------------------------------------------


def _script(paragraph_ids: list[str]) -> ReviewScript:
    return ReviewScript(
        sections=[
            ReviewSection(
                id="sec_001",
                type="hook",
                paragraphs=[
                    ReviewParagraph(
                        id=pid,
                        text="Narration for this paragraph.",
                        target_seconds=10,
                        claims=[],
                        visual_intent="s",
                    )
                    for pid in paragraph_ids
                ],
            )
        ]
    )


def _write_wav(path: Path, seconds: float, rate: int = 8000) -> None:
    """A silent mono WAV of the given length."""
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * int(rate * seconds))


def _render_manifest_harness(tmp_path: Path) -> tuple[PipelineContext, list[str]]:
    """A job at AUDIO_READY with a script and synthesized chunk files."""
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

    paragraph_ids = ["p1", "p2"]
    script = _script(paragraph_ids)
    jobs_dir = tmp_path / "jobs"
    artifacts.write_json(
        jobs_dir / "job_1" / "review" / "review-script.json",
        {"script": script.model_dump(mode="json")},
    )

    repo.save_scene(
        conn,
        "job_1",
        Scene(scene_id="scene_000001", start=0.0, end=60.0, duration=60.0),
    )
    repo.save_movie(
        conn,
        "job_1",
        Movie(
            id="movie_1",
            metadata=MovieMetadata(
                file="m.mp4",
                sha256="a" * 64,
                duration_seconds=600.0,
                width=1920,
                height=1080,
                fps=30.0,
                video_codec="h264",
            ),
        ),
    )

    # One chunk per paragraph, each with a known length.
    for chunk in plan_chunks(script, voice="default"):
        _write_wav(
            jobs_dir / "job_1" / "tts" / f"{chunk.chunk_id}.wav",
            3.0 if chunk.paragraph_id == "p1" else 7.0,
        )

    ctx = PipelineContext(
        job_id="job_1",
        jobs_dir=jobs_dir,
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
        movie_path=tmp_path / "movie.mp4",
    )
    return ctx, paragraph_ids


def test_the_render_manifest_uses_the_measured_narration(tmp_path: Path) -> None:
    """Regression: every paragraph was timed at a hard-coded 10 seconds.

    The measured durations are the only source of the segment durations, so
    the timeline, the source-footage controls and the renderer's own duration
    check were all computed against a fiction.
    """
    ctx, paragraph_ids = _render_manifest_harness(tmp_path)
    stage = _get_stage_function("render-manifest")
    assert stage is not None
    result = stage(ctx)

    manifest = result.manifest
    durations = {s.paragraph_id: s.duration for s in manifest.segments}
    assert durations == {"p1": 3.0, "p2": 7.0}
    assert manifest.total_seconds == 10.0
    assert set(durations) == set(paragraph_ids)


def test_the_render_manifest_fails_loudly_without_measured_narration(
    tmp_path: Path,
) -> None:
    """A missing chunk must be reported, not silently timed at 10 seconds."""
    ctx, _ = _render_manifest_harness(tmp_path)
    # The chunk ids are content-derived, so the missing file is named by the
    # plan rather than by a position.
    from movie_review.review.translate import load_script
    from movie_review.tts.chunks import plan_chunks

    script = load_script(ctx.jobs_dir / "job_1" / "review" / "review-script.json")
    planned = plan_chunks(script, voice="default")
    missing = ctx.jobs_dir / "job_1" / "tts" / f"{planned[1].chunk_id}.wav"
    missing.unlink()

    stage = _get_stage_function("render-manifest")
    assert stage is not None
    with pytest.raises(Exception) as excinfo:
        stage(ctx)
    assert planned[1].chunk_id in str(excinfo.value)


# ---------------------------------------------------------------------------
# The writer's word target must follow the configured speech rate
# ---------------------------------------------------------------------------


def test_the_word_target_follows_the_configured_wpm() -> None:
    """Regression: the writer was asked for 150-WPM word counts whatever was set.

    A hard-coded 150 contradicted `settings.pipeline.review.target_wpm`,
    which the reconciliation stage two stages later does use. With a
    different rate the script came out systematically short and never
    stopped asking to be expanded.
    """
    settings = load_settings()
    default_words = review_target_words(settings)

    faster = settings.model_copy(
        update={
            "pipeline": settings.pipeline.model_copy(
                update={"review": settings.pipeline.review.model_copy(update={"target_wpm": 180})}
            )
        }
    )
    assert review_target_words(faster) > default_words

    shorter = settings.model_copy(
        update={
            "pipeline": settings.pipeline.model_copy(
                update={
                    "review": settings.pipeline.review.model_copy(
                        update={"target_duration_minutes": 10}
                    )
                }
            )
        }
    )
    assert review_target_words(shorter) < default_words


# ---------------------------------------------------------------------------
# A manifest failure has to name the stage that failed
# ---------------------------------------------------------------------------


def test_a_manifest_failure_records_the_render_manifest_stage(tmp_path: Path) -> None:
    """Regression: the failure was recorded as "render".

    A resume maps a failed job back to the stage named in `failed_stage`.
    Recording "render" made the resume re-run the render stage, which then
    failed on a manifest file that had never been written -- so the job could
    not be recovered through the documented path.
    """
    harness = _harness(tmp_path)
    with pytest.raises(ManifestError):
        assemble_manifest(
            [_paragraph("p1")],
            {"p1": _clip("p1", 0.0, 5.0)},
            {"p1": 10.0},
            100.0,
            harness.ctx,
            max_total_seconds=4.0,
        )
    job = harness.ctx.manager.get("job_1")
    assert job.status is JobStatus.FAILED
    assert job.failed_stage == "render-manifest"


def test_resume_after_a_manifest_failure_reruns_the_manifest_stage(tmp_path: Path) -> None:
    """The recorded stage has to be one the pipeline can actually resume."""
    harness = _harness(tmp_path)
    with pytest.raises(ManifestError):
        assemble_manifest(
            [_paragraph("p1")],
            {"p1": _clip("p1", 0.0, 5.0)},
            {"p1": 10.0},
            100.0,
            harness.ctx,
            max_total_seconds=4.0,
        )
    plan = recovery_plan(harness.ctx.manager, "job_1")
    assert plan.resume_stage == "render-manifest"

    from movie_review.pipeline.orchestrator import STAGE_SEQUENCE

    order = [name for name, _ in STAGE_SEQUENCE]
    assert plan.resume_stage in order


def test_the_manifest_still_lands_in_the_render_directory(tmp_path: Path) -> None:
    """The stage name and the directory it writes into are different things."""
    harness = _harness(tmp_path)
    result = assemble_manifest(
        [_paragraph("p1")],
        {"p1": _clip("p1", 0.0, 5.0)},
        {"p1": 10.0},
        100.0,
        harness.ctx,
    )
    assert result.manifest_path.parent.name == "render"
