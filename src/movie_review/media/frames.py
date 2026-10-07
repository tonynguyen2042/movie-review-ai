"""Adaptive frame sampling over detected scenes (T015, README section 12).

Base sampling is duration-adaptive (short/medium/long buckets); content
boosts (motion, new characters, story events) arrive with T026 feedback.
Frames are extracted from the analysis proxy with accurate seeking.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import VisualSamplingSettings
from movie_review.domain import Artifact
from movie_review.media import ffmpeg as ff
from movie_review.pipeline.progress import ProgressReporter, WorkProgress
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "frames"
#: Bumped to v2 when frames came from the analysis proxy rather than the
#: original source. Same scenes, same timestamps, different pixels -- so the v1
#: cache entries describe images that no longer match what is produced.
STAGE_VERSION = "v2"
MANIFEST_FILENAME = "frames.json"


class FrameSamplingError(Exception):
    """Frame sampling failed in a classified way."""


@dataclass(frozen=True)
class Frame:
    """One extracted analysis frame."""

    scene_id: str
    timestamp: float
    path: Path


@dataclass(frozen=True)
class SamplingResult:
    """Outcome of one sampling run."""

    frames: list[Frame]
    manifest_path: Path
    cache_hit: bool


@dataclass(frozen=True)
class SamplingConfig:
    """Bucket boundaries and per-scene frame counts (README section 12)."""

    short_threshold: float = 10.0
    medium_threshold: float = 60.0
    short_frames: int = 3
    medium_frames: int = 6
    long_frames: int = 12

    def __post_init__(self) -> None:
        if not 0 < self.short_threshold < self.medium_threshold:
            raise ValueError("thresholds must satisfy 0 < short < medium")
        for name in ("short_frames", "medium_frames", "long_frames"):
            if getattr(self, name) < 2:
                raise ValueError(f"{name} must be at least 2")


def sampling_config_from(settings: VisualSamplingSettings) -> SamplingConfig:
    """Bridge configured sampling buckets to a :class:`SamplingConfig`."""
    return SamplingConfig(
        short_threshold=settings.short_threshold,
        medium_threshold=settings.medium_threshold,
        short_frames=settings.short_frames,
        medium_frames=settings.medium_frames,
        long_frames=settings.long_frames,
    )


def plan_count(duration: float, config: SamplingConfig | None = None) -> int:
    """Frame count bucket for a scene duration in seconds."""
    cfg = config or SamplingConfig()
    if duration < 0:
        raise FrameSamplingError(f"Negative scene duration: {duration}")
    if duration < cfg.short_threshold:
        return cfg.short_frames
    if duration < cfg.medium_threshold:
        return cfg.medium_frames
    return cfg.long_frames


def sample_timestamps(start: float, end: float, count: int) -> list[float]:
    """Evenly spaced timestamps over ``[start, end)``.

    The span end is excluded: it belongs to the next scene (or is past EOF),
    so seeking exactly there yields no frame.
    """
    if count < 2:
        raise FrameSamplingError(f"Need at least 2 samples, got {count}")
    if end <= start:
        raise FrameSamplingError(f"Invalid span [{start}, {end}]")
    step = (end - start) / count
    return [start + step * index for index in range(count)]


def frame_filename(scene_id: str, timestamp: float) -> str:
    """Deterministic frame filename embedding millisecond timestamp."""
    return f"{scene_id}-{int(round(timestamp * 1000)):08d}.jpg"


def extract_frame(
    source: str | Path,
    timestamp: float,
    dest: str | Path,
    ffmpeg: str = "ffmpeg",
    run_fn: Callable[..., str] = ff.check,
) -> Path:
    """Extract one accurate-seek JPEG frame; raises :class:`FrameSamplingError`."""
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_fn(
            ffmpeg,
            [
                "-y",
                "-v",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(target),
            ],
        )
    except ff.ProcessError as exc:
        raise FrameSamplingError(f"Cannot extract frame at {timestamp}s: {exc}") from exc
    if not target.is_file():
        raise FrameSamplingError(f"Frame extraction produced no file at {timestamp}s")
    return target


def frames_cache_key(
    file_hash: str, scenes: list[tuple[str, float, float]], cfg: SamplingConfig
) -> str:
    """Cache key for a sampling plan (shared with feedback resampling)."""
    spec = CacheSpec(
        stage=STAGE_NAME,
        stage_version=STAGE_VERSION,
        input_hash=file_hash,
        generation_config={
            "scenes": [[sid, start, end] for sid, start, end in scenes],
            "short_threshold": cfg.short_threshold,
            "medium_threshold": cfg.medium_threshold,
            "short_frames": cfg.short_frames,
            "medium_frames": cfg.medium_frames,
            "long_frames": cfg.long_frames,
        },
    )
    return cache_key(spec)


def sample_movie(
    source: str | Path,
    scenes: list[tuple[str, float, float]],
    *,
    job_id: str,
    jobs_dir: str | Path,
    conn: sqlite3.Connection,
    cache: CacheManager,
    config: SamplingConfig | None = None,
    ffmpeg: str = "ffmpeg",
    run_fn: Callable[..., str] = ff.check,
    on_progress: ProgressReporter | None = None,
) -> SamplingResult:
    """Sample frames for ``(scene_id, start, end)`` spans; skips work on cache hit.

    Reports one step per frame when ``on_progress`` is given. The total is known
    before any extraction starts -- the sum of the per-scene bucket counts -- so
    the fraction is real rather than an estimate.
    """
    cfg = config or SamplingConfig()
    src = Path(source)
    if not src.is_file():
        raise FrameSamplingError(f"Input file not found: {src}")
    # The hash is of the file frames are actually read from, not of the job's
    # original movie. Sampling the proxy and sampling the source produce
    # different pixels from identical timestamps, so the cache key has to name
    # which one produced a frame -- otherwise switching between them would
    # silently reuse the other's frames.
    file_hash = artifacts.sha256_file(src)
    key = frames_cache_key(file_hash, scenes, cfg)
    frames_dir = Path(jobs_dir) / job_id / STAGE_NAME
    # Counted up front so the reported fraction is exact, not a guess that
    # drifts when a scene lands in a different bucket than the last one.
    planned = [
        (scene_id, start, end, plan_count(end - start, cfg)) for scene_id, start, end in scenes
    ]
    total_frames = sum(count for _, _, _, count in planned)

    reusable = _reusable_by_scene(cache.lookup_json(key))

    frames: list[Frame] = []
    adopted = 0
    extracted = 0

    for scene_id, start, end, count in planned:
        # Adopt what a previous run already produced for this scene, even if it
        # lives under an earlier job directory. Re-extracting a frame that is
        # already on disk costs a decode per scene and gains nothing.
        reused = _adopt_scene(reusable.get(scene_id, []), frames_dir, scene_id)
        if reused is not None:
            frames.extend(reused)
            adopted += len(reused)
            extracted += len(reused)
            if on_progress is not None:
                on_progress(
                    WorkProgress(
                        done=extracted,
                        total=total_frames,
                        label=f"frame {extracted}/{total_frames}",
                    )
                )
            continue

        for timestamp in sample_timestamps(start, end, count):
            dest = frames_dir / scene_id / frame_filename(scene_id, timestamp)
            extract_frame(src, timestamp, dest, ffmpeg, run_fn)
            frames.append(Frame(scene_id=scene_id, timestamp=timestamp, path=dest))
            extracted += 1
            if on_progress is not None:
                on_progress(
                    WorkProgress(
                        done=extracted,
                        total=total_frames,
                        label=f"frame {extracted}/{total_frames}",
                    )
                )

        # Persisted after every scene, not once at the end: a run interrupted by
        # a crash or a full disk keeps the work already done, and the next run
        # adopts it instead of starting over. The key is computed from the full
        # scene list, so a partial manifest still matches on the retry.
        _persist(cache, key, frames_dir, job_id, frames)

    manifest_path = frames_dir / MANIFEST_FILENAME
    manifest_hash = artifacts.write_json(
        manifest_path,
        {
            "job_id": job_id,
            "stage": STAGE_NAME,
            "stage_version": STAGE_VERSION,
            "frames": _manifest_entries(frames),
        },
    )
    cache_hit = adopted == len(frames) and bool(frames)
    repo.save_artifact(
        conn,
        Artifact(
            artifact_id=f"{job_id}-frames",
            job_id=job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(
                jobs_dir, job_id, frames_dir / MANIFEST_FILENAME
            ),
            input_hash=file_hash,
            output_hash=manifest_hash,
        ),
    )
    with ulog.logging_context(job_id=job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="stage.completed",
            status="ok",
            cache_hit=cache_hit,
            frames=len(frames),
            adopted=adopted,
            extracted=len(frames) - adopted,
        )
    return SamplingResult(frames=frames, manifest_path=manifest_path, cache_hit=cache_hit)


def _manifest_entries(frames: list[Frame]) -> list[dict[str, object]]:
    """Content-addressed description of every frame produced."""
    return [
        {
            "scene_id": frame.scene_id,
            "timestamp": frame.timestamp,
            "path": str(frame.path),
            "sha256": artifacts.sha256_file(frame.path),
        }
        for frame in frames
    ]


def _persist(
    cache: CacheManager, key: str, frames_dir: Path, job_id: str, frames: list[Frame]
) -> None:
    """Write the manifest and refresh the cache pointer for what exists so far.

    Called after each completed scene rather than once at the end, so a run cut
    short by a crash or a full disk keeps the work already done. The cache key is
    computed from the full scene list, so a partial manifest still matches on the
    next attempt and the finished scenes are adopted instead of redone.
    """
    manifest = {
        "job_id": job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "frames": _manifest_entries(frames),
    }
    artifacts.write_json(frames_dir / MANIFEST_FILENAME, manifest)
    cache.store_json(key, manifest)


def _adopt_scene(
    entries: list[tuple[float, Path, str]], frames_dir: Path, scene_id: str
) -> list[Frame] | None:
    """Materialise a previously sampled scene into this job's frames directory.

    Returns ``None`` when any frame cannot be produced from cache, so the caller
    falls back to extraction for the whole scene rather than mixing sources
    mid-scene -- a scene's frames must all come from the same pass to stay
    visually coherent.

    Each frame is verified against the recorded sha256 both before and after the
    copy, so adopting from another job's directory cannot smuggle in a truncated
    or modified file. The recorded path is also required to be the filename this
    module would have produced, which keeps a stale or hand-edited cache entry
    from redirecting the copy somewhere unintended.
    """
    if not entries:
        return None
    frames: list[Frame] = []
    for timestamp, source, expected in sorted(entries):
        if source.name != frame_filename(scene_id, timestamp):
            return None
        dest = frames_dir / scene_id / frame_filename(scene_id, timestamp)
        if not (dest.is_file() and artifacts.sha256_file(dest) == expected):
            if not source.is_file() or artifacts.sha256_file(source) != expected:
                return None
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
            if artifacts.sha256_file(dest) != expected:
                return None
        frames.append(Frame(scene_id=scene_id, timestamp=timestamp, path=dest))
    return frames


def _reusable_by_scene(pointer: object) -> dict[str, list[tuple[float, Path, str]]]:
    """Group a cache pointer's frames by scene.

    Malformed entries are skipped individually rather than discarding the whole
    pointer: a partially readable manifest should still contribute the scenes it
    can vouch for.
    """
    grouped: dict[str, list[tuple[float, Path, str]]] = {}
    if not isinstance(pointer, dict):
        return grouped
    entries = pointer.get("frames")
    if not isinstance(entries, list):
        return grouped
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            scene_id = str(entry["scene_id"])
            timestamp = float(entry["timestamp"])
            path = Path(str(entry["path"]))
            expected = str(entry["sha256"])
        except (KeyError, TypeError, ValueError):
            continue
        grouped.setdefault(scene_id, []).append((timestamp, path, expected))
    return grouped
