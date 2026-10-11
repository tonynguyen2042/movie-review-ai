"""Transcript stage: audio extraction → ASR → ``transcript.json`` (T018).

Follows the pipeline stage contract with the T011 lifecycle pattern, moving
``SCENES_READY`` → ``TRANSCRIPT_READY``. The ASR backend is any
:class:`ASRPort`, chosen by :func:`build_asr_adapter` from the configured
``ModelSpec`` -- local MLX weights, or a remote OpenAI-compatible endpoint.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.asr.factory import build_asr_adapter
from movie_review.asr.port import ASRPort
from movie_review.asr.subtitles import write_sidecars
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.domain import Artifact, JobStatus, TranscriptSegment
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.media.audio import CHANNELS as AUDIO_CHANNELS
from movie_review.media.audio import SAMPLE_RATE, AudioExtractionError, extract_dialogue_audio
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "transcript"
STAGE_VERSION = "v1"
TRANSCRIPT_FILENAME = "transcript.json"
AUDIO_FILENAME = "dialogue.wav"


class TranscriptError(Exception):
    """Transcript stage failed in a classified way."""


@dataclass
class TranscriptResult:
    """Outcome of one transcript run."""

    segments: list[TranscriptSegment]
    transcript_path: Path
    audio_path: Path
    srt_path: Path
    vtt_path: Path
    cache_hit: bool
    duration_ms: int


def run_transcript(
    source: str | Path,
    ctx: StageContext,
    language: str | None = None,
    port: ASRPort | None = None,
    extract_fn: Callable[[Path, Path, str], Path] | None = None,
) -> TranscriptResult:
    """Transcribe ``source`` for ``ctx.job_id`` through to ``TRANSCRIPT_READY``."""
    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise TranscriptError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise TranscriptError(f"Job {ctx.job_id} failed; resume arrives in T085")
    owns_completion = job.status is JobStatus.SCENES_READY

    src = Path(source)
    if not src.is_file():
        raise TranscriptError(f"Input file not found: {src}")
    # The factory honours ModelSpec.backend, so `backend: openai_compatible`
    # routes to the remote endpoint and `backend: mlx` loads local weights.
    # Hardcoding WhisperMLXAdapter here ignored the configured backend and made
    # every non-Apple host fail with "mlx-whisper is not installed".
    active = port or build_asr_adapter(ctx.settings.models.asr)
    # Read from the port rather than inspecting adapter types: for a remote
    # adapter the model id is what belongs in the cache key.
    model = active.model

    audio_path = artifacts.artifact_path(ctx.jobs_dir, ctx.job_id, "audio", AUDIO_FILENAME)
    file_hash = artifacts.sha256_file(src)
    spec = CacheSpec(
        stage=STAGE_NAME,
        stage_version=STAGE_VERSION,
        input_hash=file_hash,
        model_id=model,
        generation_config={
            "language": language,
            "sample_rate": SAMPLE_RATE,
            "channels": AUDIO_CHANNELS,
        },
    )
    key = cache_key(spec)
    cached = ctx.cache.lookup_json(key)
    if cached is not None:
        try:
            segments = [TranscriptSegment.model_validate(item) for item in cached["segments"]]
        except (KeyError, TypeError, ValueError) as exc:
            if owns_completion:
                ctx.manager.fail(ctx.job_id, STAGE_NAME, f"cached transcript corrupt: {exc}")
            raise TranscriptError(f"Cached transcript.json is corrupt for {src}") from exc
        cache_hit = True
        if not audio_path.is_file():
            try:
                (extract_fn or extract_dialogue_audio)(src, audio_path, ctx.settings.media.ffmpeg)
            except AudioExtractionError as exc:
                raise TranscriptError(str(exc)) from exc
    else:
        extract = extract_fn or extract_dialogue_audio
        try:
            extract(src, audio_path, ctx.settings.media.ffmpeg)
        except AudioExtractionError as exc:
            if owns_completion:
                ctx.manager.fail(ctx.job_id, STAGE_NAME, str(exc))
            raise TranscriptError(str(exc)) from exc
        try:
            segments = active.transcribe(audio_path, language=language)
        except Exception as exc:  # Backend errors vary; classify with chaining (cf. T013).
            if owns_completion:
                ctx.manager.fail(ctx.job_id, STAGE_NAME, str(exc))
            raise TranscriptError(f"Cannot transcribe {src}: {exc}") from exc
        finally:
            active.unload()
        cache_hit = False

    repo.save_transcript_segments(ctx.conn, ctx.job_id, segments)
    document = {
        "job_id": ctx.job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "language": language,
        "model": model,
        "segments": [segment.model_dump(mode="json") for segment in segments],
    }
    transcript_path = artifacts.artifact_path(
        ctx.jobs_dir, ctx.job_id, STAGE_NAME, TRANSCRIPT_FILENAME
    )
    output_hash = artifacts.write_json(transcript_path, document)
    # Subtitle sidecars for downstream consumers (Qwen3-VL) and debugging.
    # Always regenerated — even on cache hit — so a rerun never leaves a
    # stale .srt/.vtt next to a fresh transcript.json. Same segments in give
    # byte-identical files out, keeping the stage idempotent.
    srt_path, vtt_path = write_sidecars(transcript_path.parent, segments)
    if not cache_hit:
        ctx.cache.store_json(key, document)
    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-transcript",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(
                ctx.jobs_dir, ctx.job_id, transcript_path
            ),
            input_hash=file_hash,
            output_hash=output_hash,
            model=model,
        ),
    )
    for artifact_id, sidecar in (
        (f"{ctx.job_id}-transcript-srt", srt_path),
        (f"{ctx.job_id}-transcript-vtt", vtt_path),
    ):
        repo.save_artifact(
            ctx.conn,
            Artifact(
                artifact_id=artifact_id,
                job_id=ctx.job_id,
                stage=STAGE_NAME,
                relative_path=artifacts.relative_artifact_path(ctx.jobs_dir, ctx.job_id, sidecar),
                input_hash=file_hash,
                output_hash=artifacts.sha256_file(sidecar),
                model=model,
            ),
        )

    duration_ms = int((time.perf_counter() - started) * 1000)
    with ulog.logging_context(job_id=ctx.job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="stage.completed",
            status="ok",
            duration_ms=duration_ms,
            cache_hit=cache_hit,
            segments=len(segments),
        )
    if owns_completion:
        ctx.manager.transition(ctx.job_id, JobStatus.TRANSCRIPT_READY)
    return TranscriptResult(
        segments=segments,
        transcript_path=transcript_path,
        audio_path=audio_path,
        srt_path=srt_path,
        vtt_path=vtt_path,
        cache_hit=cache_hit,
        duration_ms=duration_ms,
    )
