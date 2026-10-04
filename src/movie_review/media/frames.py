"""Adaptive frame sampling over detected scenes (T015, README section 12).

Base sampling is duration-adaptive (short/medium/long buckets); content
boosts (motion, new characters, story events) arrive with T026 feedback.
Frames are extracted from the analysis proxy with accurate seeking.
"""

from __future__ import annotations

import logging
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
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "frames"
STAGE_VERSION = "v1"
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
) -> SamplingResult:
    """Sample frames for ``(scene_id, start, end)`` spans; skips work on cache hit."""
    cfg = config or SamplingConfig()
    src = Path(source)
    if not src.is_file():
        raise FrameSamplingError(f"Input file not found: {src}")
    file_hash = artifacts.sha256_file(src)
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
    key = cache_key(spec)
    frames_dir = Path(jobs_dir) / job_id / STAGE_NAME
    pointer = cache.lookup_json(key)
    if isinstance(pointer, dict):
        frames = _verify_cached(pointer, frames_dir)
        if frames is not None:
            with ulog.logging_context(job_id=job_id, stage=STAGE_NAME):
                ulog.log_event(
                    _logger,
                    event="stage.completed",
                    status="ok",
                    cache_hit=True,
                    frames=len(frames),
                )
            return SamplingResult(
                frames=frames,
                manifest_path=frames_dir / MANIFEST_FILENAME,
                cache_hit=True,
            )

    frames = []
    for scene_id, start, end in scenes:
        count = plan_count(end - start, cfg)
        for timestamp in sample_timestamps(start, end, count):
            dest = frames_dir / scene_id / frame_filename(scene_id, timestamp)
            extract_frame(src, timestamp, dest, ffmpeg, run_fn)
            frames.append(Frame(scene_id=scene_id, timestamp=timestamp, path=dest))

    manifest = {
        "job_id": job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "frames": [
            {
                "scene_id": frame.scene_id,
                "timestamp": frame.timestamp,
                "path": str(frame.path),
                "sha256": artifacts.sha256_file(frame.path),
            }
            for frame in frames
        ],
    }
    manifest_path = frames_dir / MANIFEST_FILENAME
    manifest_hash = artifacts.write_json(manifest_path, manifest)
    cache.store_json(key, manifest)
    repo.save_artifact(
        conn,
        Artifact(
            artifact_id=f"{job_id}-frames",
            job_id=job_id,
            stage=STAGE_NAME,
            input_hash=file_hash,
            output_hash=manifest_hash,
        ),
    )
    with ulog.logging_context(job_id=job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="stage.completed",
            status="ok",
            cache_hit=False,
            frames=len(frames),
        )
    return SamplingResult(frames=frames, manifest_path=manifest_path, cache_hit=False)


def _verify_cached(pointer: dict[str, object], frames_dir: Path) -> list[Frame] | None:
    entries = pointer.get("frames")
    if not isinstance(entries, list):
        return None
    frames = []
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        try:
            path = Path(str(entry["path"]))
            timestamp = float(entry["timestamp"])
            scene_id = str(entry["scene_id"])
            expected = str(entry["sha256"])
        except (KeyError, TypeError, ValueError):
            return None
        if not path.is_file() or artifacts.sha256_file(path) != expected:
            return None
        if path.parent != frames_dir / scene_id:
            return None
        frames.append(Frame(scene_id=scene_id, timestamp=timestamp, path=path))
    return frames
