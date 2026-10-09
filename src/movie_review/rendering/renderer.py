"""FFmpeg renderer: manifest timeline → final review video (T061, spec 45-46).

Extracts per-segment clips (scaled/padded to the configured frame,
looped when narration outruns footage), concatenates, muxes narration
audio, and writes the subtitle sidecar. Output verified by probe.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.domain import Artifact, JobStatus, RenderManifest
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.media import ffmpeg as ff
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "render"
STAGE_VERSION = "v1"
REVIEW_FILENAME = "review.mp4"
SUBTITLE_FILENAME = "review.srt"


class RenderError(Exception):
    """Rendering failed in a classified way."""


@dataclass(frozen=True)
class RenderResult:
    """Rendered output with measured duration."""

    path: Path
    subtitle_path: Path | None
    duration_seconds: float
    cache_hit: bool


def _scale_pad(width: int, height: int) -> str:
    return (
        f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease,"
        f"scale=trunc(iw/2)*2:trunc(ih/2)*2,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )


def render(
    manifest: RenderManifest,
    source_movie: str | Path,
    narration_wav: str | Path,
    subtitles_srt: str | Path | None,
    dest: str | Path,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    preset: str = "veryfast",
    crf: int = 23,
    ffmpeg: str = "ffmpeg",
    run_fn: Callable[..., str] = ff.check,
    probe_fn: Callable[[str], object] = ff.probe,
) -> RenderResult:
    """Render one manifest timeline to ``dest`` with verification."""
    src = Path(source_movie)
    narration = Path(narration_wav)
    target = Path(dest)
    if not src.is_file():
        raise RenderError(f"Source movie not found: {src}")
    if not narration.is_file():
        raise RenderError(f"Narration not found: {narration}")
    if width <= 0 or height <= 0 or fps <= 0:
        raise RenderError(f"Invalid frame parameters: {width}x{height}@{fps}")
    target.parent.mkdir(parents=True, exist_ok=True)
    workdir = target.parent / "parts"
    workdir.mkdir(parents=True, exist_ok=True)

    def _run(extra_args: list[str]) -> str:
        try:
            return run_fn(ffmpeg, extra_args)
        except ff.ProcessError as exc:
            raise RenderError(f"ffmpeg failed: {exc}") from exc

    video_filter = f"{_scale_pad(width, height)},fps={fps},format=yuv420p"
    part_lists: list[str] = []
    for index, segment in enumerate(manifest.segments):
        clip_span = segment.clip_end - segment.clip_start
        if clip_span <= 0:
            raise RenderError(f"Empty clip range for {segment.paragraph_id}")
        plays = max(1, math.ceil(segment.duration / clip_span))
        part = workdir / f"seg_{index:03d}.mp4"
        if plays == 1:
            _run(
                [
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(src),
                    "-ss",
                    f"{segment.clip_start:.3f}",
                    "-t",
                    f"{segment.duration:.3f}",
                    "-vf",
                    video_filter,
                    "-c:v",
                    "libx264",
                    "-preset",
                    preset,
                    "-crf",
                    str(crf),
                    "-an",
                    str(part),
                ]
            )
        else:
            looped = part.with_suffix(".loop.mp4")
            _run(
                [
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(src),
                    "-ss",
                    f"{segment.clip_start:.3f}",
                    "-t",
                    f"{clip_span:.3f}",
                    "-vf",
                    video_filter,
                    "-c:v",
                    "libx264",
                    "-preset",
                    preset,
                    "-crf",
                    str(crf),
                    "-an",
                    str(looped),
                ]
            )
            _run(
                [
                    "-y",
                    "-v",
                    "error",
                    "-stream_loop",
                    str(plays - 1),
                    "-i",
                    str(looped),
                    "-t",
                    f"{segment.duration:.3f}",
                    "-c",
                    "copy",
                    str(part),
                ]
            )
        part_lists.append(str(part))
    concat_list = workdir / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{Path(part).as_posix()}'\n" for part in part_lists), encoding="utf-8"
    )
    video_only = workdir / "video.mp4"
    _run(
        [
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(video_only),
        ]
    )
    try:
        run_fn(
            ffmpeg,
            [
                "-y",
                "-v",
                "error",
                "-i",
                str(video_only),
                "-i",
                str(narration),
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                str(target),
            ],
        )
    except ff.ProcessError as exc:
        raise RenderError(f"Cannot mux {target}: {exc}") from exc

    resolved_subtitles: Path | None = None
    if subtitles_srt is not None:
        resolved_subtitles = target.with_name(SUBTITLE_FILENAME)
        try:
            resolved_subtitles.write_bytes(Path(subtitles_srt).read_bytes())
        except OSError as exc:
            raise RenderError(f"Cannot write subtitles: {exc}") from exc
    try:
        meta = probe_fn(str(target))
        duration = float(getattr(meta, "duration_seconds", 0.0))
    except (ff.ProbeError, ff.ProcessError, AttributeError, TypeError, ValueError) as exc:
        raise RenderError(f"Rendered output unreadable: {exc}") from exc
    if abs(duration - manifest.total_seconds) > max(2.0, manifest.total_seconds * 0.05):
        raise RenderError(
            f"Rendered {duration:.1f}s deviates from manifest {manifest.total_seconds:.1f}s"
        )
    with ulog.logging_context(stage="render"):
        ulog.log_event(_logger, event="render.completed", status="ok")
    return RenderResult(
        path=target,
        subtitle_path=resolved_subtitles,
        duration_seconds=duration,
        cache_hit=False,
    )


def _hash_file(path: str | Path, label: str) -> str:
    """SHA-256 of an input file or a classified error."""
    try:
        return artifacts.sha256_file(path)
    except OSError as exc:
        raise RenderError(f"Cannot hash {label} {path}: {exc}") from exc


def render_job(
    manifest: RenderManifest,
    source_movie: str | Path,
    narration_wav: str | Path,
    subtitles_srt: str | Path | None,
    ctx: StageContext,
    run_fn: Callable[..., str] = ff.check,
    probe_fn: Callable[[str], object] = ff.probe,
) -> RenderResult:
    """Render for a job through to ``RENDERED`` with artifact recording.

    Encoder settings always come from configuration (no shadow parameters).
    """
    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise RenderError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise RenderError(f"Job {ctx.job_id} failed; resume arrives in T085")
    owns_completion = job.status is JobStatus.EDIT_PLAN_READY

    dest = artifacts.artifact_path(ctx.jobs_dir, ctx.job_id, STAGE_NAME, REVIEW_FILENAME)
    rendering = ctx.settings.pipeline.rendering
    source_hash = _hash_file(source_movie, "source movie")
    narration_hash = _hash_file(narration_wav, "narration")
    subtitle_hash = _hash_file(subtitles_srt, "subtitles") if subtitles_srt else "none"
    manifest_key = artifacts.sha256_bytes(
        "|".join(
            [
                source_hash,
                narration_hash,
                subtitle_hash,
                *(
                    f"{s.paragraph_id}:{s.scene_id}:{s.start:.3f}:"
                    f"{s.clip_start:.3f}:{s.clip_end:.3f}:{s.duration:.3f}"
                    for s in manifest.segments
                ),
                f"{manifest.total_seconds:.3f}",
            ]
        ).encode()
    )
    key = cache_key(
        CacheSpec(
            stage=STAGE_NAME,
            stage_version=STAGE_VERSION,
            input_hash=manifest_key,
            generation_config={
                "width": rendering.width,
                "height": rendering.height,
                "fps": rendering.fps,
                "preset": rendering.preset,
                "crf": rendering.crf,
            },
        )
    )
    pointer = ctx.cache.lookup_json(key)
    if (
        isinstance(pointer, dict)
        and dest.is_file()
        and pointer.get("output_hash") == artifacts.sha256_file(dest)
    ):
        if owns_completion:
            ctx.manager.transition(ctx.job_id, JobStatus.RENDERED)
        return RenderResult(
            path=dest,
            subtitle_path=dest.with_name(SUBTITLE_FILENAME) if subtitles_srt else None,
            duration_seconds=manifest.total_seconds,
            cache_hit=True,
        )
    try:
        result = render(
            manifest,
            source_movie,
            narration_wav,
            subtitles_srt,
            dest,
            width=rendering.width,
            height=rendering.height,
            fps=rendering.fps,
            preset=rendering.preset,
            crf=rendering.crf,
            ffmpeg=ctx.settings.media.ffmpeg,
            run_fn=run_fn,
            probe_fn=probe_fn,
        )
    except RenderError as exc:
        if owns_completion:
            ctx.manager.fail(ctx.job_id, STAGE_NAME, str(exc))
        raise
    except Exception as exc:
        if owns_completion:
            ctx.manager.fail(ctx.job_id, STAGE_NAME, f"unexpected: {exc}")
        raise RenderError(f"Render failed: {exc}") from exc
    ctx.cache.store_json(key, {"output_hash": artifacts.sha256_file(dest)})
    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-review",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(ctx.jobs_dir, ctx.job_id, dest),
            input_hash=artifacts.sha256_file(dest),
            output_hash=artifacts.sha256_file(dest),
        ),
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    with ulog.logging_context(job_id=ctx.job_id, stage=STAGE_NAME):
        ulog.log_event(_logger, event="stage.completed", status="ok", duration_ms=duration_ms)
    if owns_completion:
        ctx.manager.transition(ctx.job_id, JobStatus.RENDERED)
    return result
