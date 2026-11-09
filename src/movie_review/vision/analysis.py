"""Scene visual analysis stage: frames + dialogue → VLM → ``vision.json`` (T025).

Follows the pipeline stage contract with the T011 lifecycle pattern, moving
``TRANSCRIPT_READY`` → ``VISUAL_ANALYSIS_READY``. Each scene is analyzed
independently with a small context window (its frames, overlapping dialogue,
previous scene summary) per P3. Per-scene caching makes reruns cheap. The VLM
is chosen by :func:`build_vlm_adapter` from the configured ``ModelSpec`` --
local MLX weights, or a remote OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
import logging
import time
from bisect import bisect_left, bisect_right
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.config.prompts import Prompt, load_prompt, render
from movie_review.domain import Artifact, JobStatus, Scene, SceneAnalysis, TranscriptSegment
from movie_review.jobs.failure import job_failure_message
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.models.resources import run_with_oom_recovery
from movie_review.pipeline.context import StageContext
from movie_review.pipeline.progress import ProgressReporter, WorkProgress
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog
from movie_review.vision.factory import build_vlm_adapter
from movie_review.vision.port import AnalysisInput, VLMPort

_logger = logging.getLogger(__name__)

STAGE_NAME = "vision"
STAGE_VERSION = "v1"
VISION_FILENAME = "vision.json"
MAX_DIALOGUE_CHARS = 2000

#: How many scenes are analysed at once. The scenes in a batch run
#: concurrently; the batch before it supplies the continuity context.
DEFAULT_BATCH_SIZE = 8

#: How many scenes are analysed at the same time. A remote endpoint can
#: usually take a few requests at once; a local one can take as many as
#: the machine has cores for.
DEFAULT_CONCURRENCY = 4

#: The most frames one request may carry. The orchestrator always passes the
#: configured ``ModelSpec.max_frames_per_request``; this default serves direct
#: callers and must stay equal to the ModelSpec fallback.
DEFAULT_MAX_FRAMES_PER_REQUEST = 32


@dataclass(frozen=True)
class _BatchEntry:
    """One scene's outcome."""

    analysis: SceneAnalysis
    cache_hit: bool


def _batches(scenes: list[Scene], size: int) -> list[list[Scene]]:
    """Split the scenes into batches of at most ``size``."""
    if size <= 1:
        return [[scene] for scene in scenes]
    return [scenes[index : index + size] for index in range(0, len(scenes), size)]


def _request_frames(frames: list[Path], max_frames: int) -> list[Path]:
    """The frames one request carries: never more than ``max_frames``.

    A scene keeps every frame it sampled, but the endpoint may refuse more
    images than the cap in a single request. Over the cap, the request keeps
    the first and the last frame and spaces the rest evenly over the scene,
    so it still covers the whole span in chronological order. The frames that
    do not ride the request stay on disk and in the manifest.
    """
    if len(frames) <= max_frames:
        return list(frames)
    if max_frames <= 1:
        return [frames[len(frames) // 2]]
    step = (len(frames) - 1) / (max_frames - 1)
    return [frames[round(index * step)] for index in range(max_frames)]


def _analyse_one(
    scene: Scene,
    scene_frames: list[Path],
    dialogue: str,
    summary: str,
    input_summary: str | None,
    prompt: Prompt,
    model: str,
    active: VLMPort,
    ctx: StageContext,
    max_frames: int,
) -> _BatchEntry:
    """Analyse one scene: cache lookup, then the model."""
    # The request carries at most max_frames of the scene's frames (T181);
    # the prompt and the cache key describe what the request carries.
    request_frames = _request_frames(scene_frames, max_frames)
    text = render(
        prompt,
        scene_id=scene.scene_id,
        frame_count=str(len(request_frames)),
        metadata=f"{scene.duration:.1f}s, {len(request_frames)} frames",
        dialogue=dialogue or "(no dialogue)",
        previous_summary=summary,
    )
    spec = CacheSpec(
        stage=STAGE_NAME,
        stage_version=STAGE_VERSION,
        input_hash=_scene_input_hash(scene, scene_frames, dialogue, summary, max_frames),
        model_id=model,
        prompt_version=prompt.cache_version,
    )
    key = cache_key(spec)
    cached = ctx.cache.lookup_json(key)
    if cached is not None:
        try:
            analysis = SceneAnalysis.model_validate(cached["analysis"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VisualAnalysisError(f"Cached vision is corrupt for {scene.scene_id}") from exc
        _audit_response(
            scene, scene_frames, request_frames, max_frames, ctx, model, analysis, cache_hit=True
        )
        return _BatchEntry(analysis=analysis, cache_hit=True)

    started = time.perf_counter()
    try:
        analysis = run_with_oom_recovery(
            lambda: active.analyze(
                AnalysisInput(
                    scene_id=scene.scene_id,
                    frames=request_frames,
                    dialogue=dialogue,
                    previous_summary=input_summary,
                ),
                text,
            ),
            active.unload,
            attempts=2,
            stage=STAGE_NAME,
        )
    except Exception as exc:
        raise VisualAnalysisError(f"Cannot analyze {scene.scene_id}: {exc}") from exc
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    ctx.cache.store_json(key, {"analysis": analysis.model_dump(mode="json")})
    _audit_response(
        scene,
        scene_frames,
        request_frames,
        max_frames,
        ctx,
        model,
        analysis,
        cache_hit=False,
        duration_ms=elapsed_ms,
    )
    return _BatchEntry(analysis=analysis, cache_hit=False)


def _audit_response(
    scene: Scene,
    scene_frames: list[Path],
    request_frames: list[Path],
    max_frames: int,
    ctx: StageContext,
    model: str,
    analysis: SceneAnalysis,
    *,
    cache_hit: bool,
    duration_ms: int | None = None,
) -> None:
    """One line per scene answering "what did the VLM get, and what did it say".

    ``frames_sent`` is the audit number (T184): the exact frames the request
    carried, and the very list the port encodes and sends. Alongside it,
    ``frames_sampled`` (what the scene sampled before the cap) and
    ``max_frames`` (the cap applied), so a reader can tell an untouched
    request from a capped subset at a glance.

    The response is not thrown away: it rides the event to the console and
    is written under the job, so a suspicious answer can be inspected
    without re-running the model. Cache hits are audited too, without a
    response payload and without touching the file a real request wrote.
    """
    response_path = ctx.jobs_dir / ctx.job_id / "vision" / "responses" / f"{scene.scene_id}.json"
    analysis_dump = analysis.model_dump(mode="json")
    response_text = json.dumps(analysis_dump, ensure_ascii=False)
    if not cache_hit:
        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(
            json.dumps(
                {
                    "scene_id": scene.scene_id,
                    "model": model,
                    "frames_sent": len(request_frames),
                    "frame_files": [path.name for path in request_frames],
                    "response": analysis_dump,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    ulog.log_event(
        _logger,
        "vision.response",
        "ok",
        duration_ms=duration_ms,
        scene_id=scene.scene_id,
        model=model,
        frames_sent=len(request_frames),
        frames_sampled=len(scene_frames),
        max_frames=max_frames,
        cache_hit=cache_hit,
        response_file=str(response_path) if response_path.is_file() else None,
        response=None if cache_hit else response_text,
    )


def _analyse_batch(
    batch: list[Scene],
    frames: dict[str, list[Path]],
    dialogue_index: DialogueIndex,
    prompt: Prompt,
    model: str,
    previous_summaries: list[str],
    active: VLMPort,
    ctx: StageContext,
    max_frames: int,
) -> list[_BatchEntry]:
    """Analyse a batch of scenes concurrently, preserving their order.

    The continuity context is the previous batch's summary, so every scene in
    the batch is told the same thing about what came before it.
    """
    if not batch:
        return []

    # The first batch has no previous scene, and says so in the prompt --
    # the same wording the serial version used.
    has_previous = bool(previous_summaries)
    summary = previous_summaries[-1] if has_previous else "none (first scene)"
    input_summary = summary if has_previous else None

    def work(scene: Scene) -> _BatchEntry:
        scene_frames = frames.get(scene.scene_id, [])
        if not scene_frames:
            raise VisualAnalysisError(f"No frames for {scene.scene_id}")
        dialogue = _join_dialogue(dialogue_index.window(scene.start, scene.end))
        return _analyse_one(
            scene,
            scene_frames,
            dialogue,
            summary,
            input_summary,
            prompt,
            model,
            active,
            ctx,
            max_frames,
        )

    if len(batch) == 1 or DEFAULT_CONCURRENCY <= 1:
        return [work(scene) for scene in batch]

    with ThreadPoolExecutor(max_workers=min(DEFAULT_CONCURRENCY, len(batch))) as pool:
        # `map` keeps the order of the input, so the results line up with the
        # scenes no matter which finished first.
        return list(pool.map(work, batch))


class VisualAnalysisError(Exception):
    """Visual analysis stage failed in a classified way."""


@dataclass
class VisualAnalysisResult:
    """Outcome of one visual analysis run."""

    analyses: list[SceneAnalysis]
    vision_path: Path
    cache_hits: int
    duration_ms: int


class DialogueIndex:
    """The transcript, indexed for the scene windows.

    The dialogue of a scene used to be found by scanning the whole
    transcript for every scene: a thousand scenes times twenty-five hundred
    segments is two and a half million iterations, and the stage that did
    it ran twice.

    The index is built once and the window is found with two bisects, so
    the cost of a scene does not grow with the length of the film.
    """

    def __init__(self, segments: list[TranscriptSegment]) -> None:
        ordered = sorted(segments, key=lambda s: (s.start, s.end))
        self._segments = ordered
        self._starts = [segment.start for segment in ordered]
        # The running maximum of the end times. It is non-decreasing, so a
        # bisect on it finds the last segment that could still be running
        # when the window opens.
        running = 0.0
        max_end: list[float] = []
        for segment in ordered:
            running = max(running, segment.end)
            max_end.append(running)
        self._max_end = max_end

    def window(self, start: float, end: float) -> list[TranscriptSegment]:
        """The segments overlapping ``[start, end)``."""
        first = bisect_right(self._max_end, start)
        last = bisect_left(self._starts, end)
        if last < first:
            last = first
        return [
            segment
            for segment in self._segments[first:last]
            if segment.start < end and segment.end > start
        ]


def _join_dialogue(segments: list[TranscriptSegment]) -> str:
    """Join the text of a window's segments, truncated for the prompt."""
    joined = " ".join(segment.text for segment in segments if segment.text.strip())
    if len(joined) > MAX_DIALOGUE_CHARS:
        return joined[:MAX_DIALOGUE_CHARS] + "\u2026"
    return joined


def scene_dialogue(segments: list[TranscriptSegment], start: float, end: float) -> str:
    """Join segment texts overlapping ``[start, end)``, truncated for prompts."""
    texts = [segment.text for segment in segments if segment.start < end and segment.end > start]
    joined = " ".join(text for text in texts if text.strip())
    if len(joined) > MAX_DIALOGUE_CHARS:
        return joined[:MAX_DIALOGUE_CHARS] + "…"
    return joined


def previous_summary(analysis: SceneAnalysis | None) -> str:
    """One-line prior-scene context for the next prompt."""
    if analysis is None:
        return "none (first scene)"
    actions = "; ".join(analysis.actions[:3])
    return f"{analysis.location}: {actions}" if actions else analysis.location or "nothing notable"


def run_visual_analysis(
    scenes: list[Scene],
    frames: dict[str, list[Path]],
    segments: list[TranscriptSegment],
    ctx: StageContext,
    port: VLMPort | None = None,
    prompt_version: str | None = None,
    on_progress: ProgressReporter | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_frames: int = DEFAULT_MAX_FRAMES_PER_REQUEST,
) -> VisualAnalysisResult:
    """Analyze scenes for ``ctx.job_id`` through to ``VISUAL_ANALYSIS_READY``.

    Reports one step per scene when ``on_progress`` is given. This is the longest
    stage in the pipeline -- one VLM call per scene, each with its own network
    round trip -- so a per-scene fraction is what tells the user it is moving.

    The scenes are analysed in batches of ``batch_size``; the scenes in a batch
    are analysed concurrently.

    ``max_frames`` caps what a single request carries (T181): a scene with more
    frames is sent with its first and last frames and the rest spaced evenly.
    The cap joins the per-scene cache key, so changing it re-analyses instead
    of adopting an answer the other cap produced.
    """
    if max_frames < 1:
        raise VisualAnalysisError(f"max_frames_per_request must be at least 1, got {max_frames}")
    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise VisualAnalysisError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise VisualAnalysisError(job_failure_message(job))
    owns_completion = job.status is JobStatus.TRANSCRIPT_READY

    prompt = load_prompt("scene_analysis", prompt_version)
    # build_vlm_adapter honours ModelSpec.backend, so a remote VLM is reachable
    # without MLX installed. Hardcoding QwenVLAdapter ignored the configuration.
    active = port or build_vlm_adapter(ctx.settings.models.vision)
    # From the port, not the adapter type: a remote adapter's real model id must
    # reach the cache key, otherwise every remote run keys on the class name.
    model = active.model

    analyses: list[SceneAnalysis] = []
    cache_hits = 0
    # The continuity context: each scene is told what the scene before it
    # showed. Analysing strictly one after another made the stage one round
    # trip per scene -- for a 2 h film, about 1000 sequential calls, which
    # at 3 s each is fifty minutes of pure serial latency with the machine
    # idle.
    #
    # The scenes are analysed in batches instead. Within a batch they run
    # concurrently and each one is told about the batch before it, so the
    # continuity still crosses the scenes; the scene immediately before it
    # inside the same batch is not in the context, which is the trade.
    previous_summaries: list[str] = []
    # The transcript is indexed once: the dialogue of every scene is found
    # with two bisects instead of a scan of the whole transcript.
    dialogue_index = DialogueIndex(segments)
    try:
        for batch in _batches(scenes, batch_size):  # noqa: B007
            results = _analyse_batch(
                batch,
                frames,
                dialogue_index,
                prompt,
                model,
                previous_summaries,
                active,
                ctx,
                max_frames,
            )
            for entry in results:
                if entry.cache_hit:
                    cache_hits += 1
                analyses.append(entry.analysis)
            # The next batch is told about the last scene of this one.
            previous_summaries = [previous_summary(results[-1].analysis)] if results else []
            if on_progress is not None:
                # Reported after a batch is fully done, so the count only
                # advances on work that actually completed.
                on_progress(
                    WorkProgress(
                        done=len(analyses),
                        total=len(scenes),
                        label=f"scene {len(analyses)}/{len(scenes)}",
                    )
                )
    except Exception as exc:
        if owns_completion:
            # The workers raise; the failure is recorded here, from the
            # thread that owns the connection.
            ctx.manager.fail(ctx.job_id, STAGE_NAME, str(exc))
        raise
    finally:
        active.unload()

    document = {
        "job_id": ctx.job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "prompt": prompt.cache_version,
        "model": model,
        "analyses": [analysis.model_dump(mode="json") for analysis in analyses],
    }
    vision_path = artifacts.artifact_path(ctx.jobs_dir, ctx.job_id, STAGE_NAME, VISION_FILENAME)
    output_hash = artifacts.write_json(vision_path, document)
    # Persisted per scene as well as in the document. Four downstream stages need
    # these analyses and every one of them used to reopen vision.json and
    # re-validate the same objects; a query is both cheaper and the reason a
    # job's visual analysis survives a deleted or moved artifact directory.
    # One transaction for the whole stage: the vision stage writes one row
    # per scene, and each write was its own commit.
    repo.save_scene_analyses(ctx.conn, ctx.job_id, analyses)
    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-vision",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(ctx.jobs_dir, ctx.job_id, vision_path),
            input_hash=_run_input_hash(scenes),
            output_hash=output_hash,
            model=model,
            prompt_version=prompt.cache_version,
        ),
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    with ulog.logging_context(job_id=ctx.job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="stage.completed",
            status="ok",
            duration_ms=duration_ms,
            cache_hits=cache_hits,
            scenes=len(analyses),
        )
    if owns_completion:
        ctx.manager.transition(ctx.job_id, JobStatus.VISUAL_ANALYSIS_READY)
    return VisualAnalysisResult(
        analyses=analyses,
        vision_path=vision_path,
        cache_hits=cache_hits,
        duration_ms=duration_ms,
    )


def _scene_input_hash(
    scene: Scene, scene_frames: list[Path], dialogue: str, summary: str, max_frames: int
) -> str:
    # The cap joins the key because it changes which subset of the frames the
    # request carries: an answer produced under one cap is not the answer the
    # other cap would have produced.
    parts = [
        scene.scene_id,
        f"{scene.start:.3f}",
        f"{scene.end:.3f}",
        dialogue,
        summary,
        f"max_frames={max_frames}",
    ]
    for frame in scene_frames:
        parts.append(artifacts.sha256_file(frame))
    return artifacts.sha256_bytes("|".join(parts).encode("utf-8"))


def _run_input_hash(scenes: list[Scene]) -> str:
    return artifacts.sha256_bytes(
        "|".join(f"{scene.scene_id}:{scene.start:.3f}:{scene.end:.3f}" for scene in scenes).encode(
            "utf-8"
        )
    )
