"""T061 acceptance: command construction, verification, and lifecycle."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import (
    Job,
    JobStatus,
    ManifestSegment,
    RenderManifest,
)
from movie_review.jobs.manager import JobManager
from movie_review.media import ffmpeg as ff
from movie_review.pipeline.context import StageContext
from movie_review.rendering.renderer import RenderError, RenderResult, render, render_job
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from tests.helpers import (
    _manifest,
    _meta,
)


class _FakeRun:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, binary: str, args: list[str]) -> str:
        self.commands.append([binary, *args])
        output = Path(args[-1])
        if output.suffix in (".mp4", ".wav", ".txt"):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"v")
        return ""


def _files(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "src.mp4"
    source.write_bytes(b"source")
    narration = tmp_path / "n.wav"
    narration.write_bytes(b"n" * 100)
    return source, narration


def test_command_construction(tmp_path: Path) -> None:
    fake = _FakeRun()
    source, narration = _files(tmp_path)
    result = render(
        _manifest(),
        source,
        narration,
        None,
        tmp_path / "review.mp4",
        run_fn=fake,
        probe_fn=lambda path: _meta(6.0),
    )
    flat = [token for command in fake.commands for token in command]
    assert "-vf" in flat
    assert any("pad=1920:1080" in token for token in flat)
    assert "libx264" in flat and "aac" in flat
    assert "-stream_loop" in flat
    assert result.duration_seconds == pytest.approx(6.0)
    assert result.cache_hit is False


def test_missing_inputs_rejected(tmp_path: Path) -> None:
    fake = _FakeRun()
    with pytest.raises(RenderError, match="Source movie not found"):
        render(
            _manifest(),
            tmp_path / "absent.mp4",
            tmp_path / "n.wav",
            None,
            tmp_path / "o.mp4",
            run_fn=fake,
            probe_fn=lambda p: _meta(6.0),
        )
    _, narration = _files(tmp_path)
    with pytest.raises(RenderError, match="Bad frame|Invalid frame"):
        render(
            _manifest(),
            tmp_path / "src.mp4",
            narration,
            None,
            tmp_path / "o.mp4",
            width=0,
            run_fn=fake,
            probe_fn=lambda p: _meta(6.0),
        )


def test_duration_mismatch_rejected(tmp_path: Path) -> None:
    fake = _FakeRun()
    source, narration = _files(tmp_path)
    with pytest.raises(RenderError, match="deviates from manifest"):
        render(
            _manifest(),
            source,
            narration,
            None,
            tmp_path / "o.mp4",
            run_fn=fake,
            probe_fn=lambda p: _meta(60.0),
        )


@dataclass
class Harness:
    conn: sqlite3.Connection
    ctx: StageContext

    def render(
        self,
        manifest: RenderManifest,
        source: Path,
        narration: Path,
        run_fn: Callable[..., str],
    ) -> RenderResult:
        return render_job(
            manifest,
            source,
            narration,
            None,
            self.ctx,
            run_fn=run_fn,
            probe_fn=lambda path: _meta(6.0),
        )


def _harness__renderer(tmp_path: Path) -> Harness:
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
        JobStatus.EDIT_PLAN_READY,
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


def test_render_job_lifecycle_and_cache(tmp_path: Path) -> None:
    harness = _harness__renderer(tmp_path)
    fake = _FakeRun()
    source, narration = _files(tmp_path)
    first = harness.render(_manifest(), source, narration, fake)
    assert first.cache_hit is False
    assert first.subtitle_path is None
    assert harness.ctx.manager.get("job_1").status is JobStatus.RENDERED
    assert repo.get_artifact(harness.conn, "job_1-review") is not None

    def _boom(binary: str, args: list[str]) -> str:
        raise AssertionError("ffmpeg must not run on cache hit")

    second = harness.render(_manifest(), source, narration, _boom)
    assert second.cache_hit is True


def test_render_job_failure_fails_job(tmp_path: Path) -> None:
    harness = _harness__renderer(tmp_path)
    source, narration = _files(tmp_path)

    def _fail(binary: str, args: list[str]) -> str:
        raise ff.ProcessError(binary, args, "boom")

    with pytest.raises(RenderError):
        harness.render(_manifest(), source, narration, _fail)
    job = harness.ctx.manager.get("job_1")
    assert job.status is JobStatus.FAILED
    assert job.failed_stage == "render"


@pytest.mark.ffmpeg
def test_render_real_end_to_end(tmp_path: Path) -> None:
    source = tmp_path / "src.mp4"
    ff.check(
        "ffmpeg",
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=25:duration=4",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-an",
            str(source),
        ],
    )
    narration = tmp_path / "n.wav"
    ff.check(
        "ffmpeg",
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=4",
            "-c:a",
            "pcm_s16le",
            str(narration),
        ],
    )
    manifest = RenderManifest(
        segments=[
            ManifestSegment(
                paragraph_id="p1",
                start=0.0,
                duration=4.0,
                scene_id="s1",
                clip_start=0.0,
                clip_end=2.0,
            ),
        ],
        total_seconds=4.0,
        source_seconds=2.0,
    )
    result = render(manifest, source, narration, None, tmp_path / "review.mp4")
    assert result.path.is_file()
    meta = ff.probe(str(result.path))
    assert (meta.width, meta.height) == (1920, 1080)
    assert meta.duration_seconds == pytest.approx(4.0, abs=0.5)
