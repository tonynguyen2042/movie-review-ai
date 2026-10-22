"""Analysis proxy generation (T012, README section 10).

Produces a small 720p H.264 proxy so later stages never repeatedly decode the
original source. Idempotency comes from the artifact record plus a tiny cache
pointer (the proxy itself is too large to duplicate into the cache).
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
from movie_review.domain import Artifact, MovieMetadata
from movie_review.media import ffmpeg as ff
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "proxy"
STAGE_VERSION = "v1"
PROXY_FILENAME = "proxy.mp4"


class ProxyError(Exception):
    """Proxy generation failed in a classified way."""


@dataclass
class ProxyResult:
    """Outcome of one proxy run."""

    path: Path
    width: int
    height: int
    cache_hit: bool


def _scale_filter(max_width: int, max_height: int) -> str:
    """Downscale into a box, never onto an odd pixel.

    ``force_original_aspect_ratio=decrease`` fits the source into the box and
    rounds each side on its own, so 1920x1080 in an 854x480 box lands on
    853x480. ``libx264`` with ``yuv420p`` rejects an odd side -- "width not
    divisible by 2" -- and the run dies at the proxy before a single frame is
    sampled, even though the box itself is a perfectly reasonable size.
    ``force_divisible_by=2`` rounds both sides to the nearest even value
    instead, which is why 854x480 yields 852x480 rather than failing.
    """
    return (
        f"scale=w={max_width}:h={max_height}"
        ":force_original_aspect_ratio=decrease"
        ":force_divisible_by=2"
    )


def generate_proxy(
    source: str | Path,
    *,
    job_id: str,
    jobs_dir: str | Path,
    conn: sqlite3.Connection,
    cache: CacheManager,
    max_width: int = 1280,
    max_height: int = 720,
    preset: str = "veryfast",
    crf: int = 23,
    ffmpeg: str = "ffmpeg",
    run_fn: Callable[..., str] = ff.check,
    probe_fn: Callable[[str], MovieMetadata] = ff.probe,
) -> ProxyResult:
    """Generate (or reuse) the analysis proxy for one job's source file."""
    if max_width <= 0 or max_height <= 0:
        raise ProxyError(f"Invalid proxy dimensions: {max_width}x{max_height}")
    if not 0 <= crf <= 51:
        raise ProxyError(f"Invalid CRF (0-51): {crf}")
    src = Path(source)
    if not src.is_file():
        raise ProxyError(f"Input file not found: {src}")

    file_hash = artifacts.sha256_file(src)
    spec = CacheSpec(
        stage=STAGE_NAME,
        stage_version=STAGE_VERSION,
        input_hash=file_hash,
        generation_config={
            "max_width": max_width,
            "max_height": max_height,
            "preset": preset,
            "crf": crf,
        },
    )
    key = cache_key(spec)
    dest = artifacts.artifact_path(jobs_dir, job_id, "media", PROXY_FILENAME)
    dest.parent.mkdir(parents=True, exist_ok=True)

    pointer = cache.lookup_json(key)
    if (
        isinstance(pointer, dict)
        and dest.is_file()
        and pointer.get("output_hash") == artifacts.sha256_file(dest)
    ):
        meta = probe_fn(str(dest))
        with ulog.logging_context(job_id=job_id, stage=STAGE_NAME):
            ulog.log_event(_logger, event="stage.completed", status="ok", cache_hit=True)
        return ProxyResult(path=dest, width=meta.width, height=meta.height, cache_hit=True)

    try:
        run_fn(
            ffmpeg,
            [
                "-y",
                "-v",
                "error",
                "-i",
                str(src),
                "-vf",
                _scale_filter(max_width, max_height),
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(dest),
            ],
        )
    except ff.ProcessError as exc:
        raise ProxyError(f"Cannot generate proxy for {src}: {exc}") from exc
    try:
        meta = probe_fn(str(dest))
    except (ff.ProbeError, ff.ProcessError) as exc:
        raise ProxyError(f"Generated proxy is unreadable: {exc}") from exc

    output_hash = artifacts.sha256_file(dest)
    cache.store_json(key, {"output_hash": output_hash})
    repo.save_artifact(
        conn,
        Artifact(
            artifact_id=f"{job_id}-proxy-video",
            job_id=job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(jobs_dir, job_id, dest),
            input_hash=file_hash,
            output_hash=output_hash,
        ),
    )
    with ulog.logging_context(job_id=job_id, stage=STAGE_NAME):
        ulog.log_event(_logger, event="stage.completed", status="ok", cache_hit=False)
    return ProxyResult(path=dest, width=meta.width, height=meta.height, cache_hit=False)
