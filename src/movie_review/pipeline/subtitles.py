"""Write the subtitle sidecar from the render manifest.

T143. `rendering/subtitles.py` was complete and tested, and nothing called
it. `review.srt` -- a required output of v1.0 -- was never produced; the
renderer only copied a sidecar if it happened to exist.

README section 47 also forbids estimating the subtitle duration from the
word count, so the cues are built from the manifest's real segment
timings, which are themselves measured from the narration.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.domain import Artifact, ReviewScript
from movie_review.pipeline.context import StageContext
from movie_review.rendering.manifest import read_manifest
from movie_review.rendering.subtitles import build_cues, write_srt
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "subtitles"
STAGE_VERSION = "v1"
SUBTITLE_FILENAME = "review.srt"


class SubtitleStageError(Exception):
    """The subtitle stage failed in a classified way."""


@dataclass
class SubtitleResult:
    """The subtitles that were written."""

    srt_path: Path
    cue_count: int
    duration_ms: int


def write_subtitles(
    manifest_path: Path,
    script: ReviewScript,
    ctx: StageContext,
) -> SubtitleResult:
    """Write ``review.srt`` beside the render manifest.

    The cues come from the manifest's segment timings, so they follow the
    narration that was actually synthesized.
    """
    started = time.perf_counter()
    if not manifest_path.is_file():
        raise SubtitleStageError(f"No render manifest at {manifest_path}")

    manifest = read_manifest(manifest_path)
    texts = {
        paragraph.id: paragraph.text
        for section in script.sections
        for paragraph in section.paragraphs
    }
    cues = build_cues(manifest, texts)
    if not cues:
        raise SubtitleStageError("The script produced no subtitle text")

    srt_path = artifacts.artifact_path(ctx.jobs_dir, ctx.job_id, "render", SUBTITLE_FILENAME)
    write_srt(srt_path, cues)

    output_hash = artifacts.sha256_file(srt_path)
    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-subtitles",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(ctx.jobs_dir, ctx.job_id, srt_path),
            input_hash=output_hash,
            output_hash=output_hash,
        ),
    )

    duration_ms = int((time.perf_counter() - started) * 1000)
    with ulog.logging_context(job_id=ctx.job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="stage.completed",
            status="ok",
            duration_ms=duration_ms,
            cues=len(cues),
        )

    return SubtitleResult(srt_path=srt_path, cue_count=len(cues), duration_ms=duration_ms)
