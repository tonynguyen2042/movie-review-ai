"""Adaptive frame sampling over detected scenes (T015, README section 12).

Base sampling is duration-adaptive (short/medium/long buckets); content
boosts (motion, new characters, story events) arrive with T026 feedback.
Frames are extracted from the analysis proxy. Each scene's sample set is one
FFmpeg decode pass (T179): a ``select`` filter keeps the scene's frames by
index and writes them in stream order, so N frames cost one launch and one
seek instead of N launches and N seeks.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import VisualSamplingSettings
from movie_review.domain import Artifact
from movie_review.media import ffmpeg as ff
from movie_review.media import fingerprint
from movie_review.pipeline.progress import ProgressReporter, WorkProgress
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "frames"
#: Bumped to v3 when a scene's frames started coming from one decode pass
#: (T179). The pass addresses frames by index, and ``round(t * fps)`` can
#: land a frame either side of the millisecond-quantised seek v2 used, so a
#: v2 cache entry may describe a neighbouring frame rather than the one
#: produced now.
STAGE_VERSION = "v3"
MANIFEST_FILENAME = "frames.json"


class FrameSamplingError(Exception):
    """Frame sampling failed in a classified way."""


@dataclass(frozen=True)
class Frame:
    """One extracted analysis frame.

    The frame's digest is carried with it. The manifest used to re-hash
    every frame it listed, and the manifest was written after every scene,
    so a frame was hashed once per scene that followed it -- quadratic in the
    number of frames, and the dominant cost of the stage.

    ``dhash`` is the frame's perceptual hash (T180), when one was computed:
    it is what lets a resumed run drop the same frames a fresh run would.
    """

    scene_id: str
    timestamp: float
    path: Path
    sha256: str = ""
    dhash: str = ""


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
    #: Drop near-duplicate frames after sampling (T180).
    dedupe: bool = True
    #: dHash bits: frames differing by at most this many bits are duplicates.
    dedupe_hamming_threshold: int = fingerprint.DEFAULT_HAMMING_THRESHOLD

    def __post_init__(self) -> None:
        if not 0 < self.short_threshold < self.medium_threshold:
            raise ValueError("thresholds must satisfy 0 < short < medium")
        for name in ("short_frames", "medium_frames", "long_frames"):
            if getattr(self, name) < 2:
                raise ValueError(f"{name} must be at least 2")
        if self.dedupe_hamming_threshold < 0:
            raise ValueError("dedupe_hamming_threshold must be >= 0")


def sampling_config_from(settings: VisualSamplingSettings) -> SamplingConfig:
    """Bridge configured sampling buckets to a :class:`SamplingConfig`."""
    return SamplingConfig(
        short_threshold=settings.short_threshold,
        medium_threshold=settings.medium_threshold,
        short_frames=settings.short_frames,
        medium_frames=settings.medium_frames,
        long_frames=settings.long_frames,
        dedupe=settings.dedupe,
        dedupe_hamming_threshold=settings.dedupe_hamming_threshold,
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


def frame_index_for(timestamp: float, fps: float) -> int:
    """The frame index nearest a requested instant.

    The batch pass addresses frames by index because the ``select`` filter
    has no time base. ``round(t * fps)`` is the index of the frame whose
    centre is closest to the requested instant. The per-frame path seeks a
    millisecond-quantised timestamp and may land one frame either side; the
    difference is below the granularity the analysis can use.
    """
    if fps <= 0:
        raise FrameSamplingError(f"Invalid fps: {fps}")
    return int(round(timestamp * fps))


def _select_expression(indices: list[int]) -> str:
    """A ``select`` filter that keeps exactly the given frame indices.

    A comma separates filters in a filter chain, so each ``eq(n, IDX)``
    escapes its comma at the filtergraph level.
    """
    return "+".join(f"eq(n\\,{index})" for index in indices)


def _per_frame(
    source: str | Path,
    timestamps: Sequence[float],
    dest_dir: Path,
    scene_id: str,
    ffmpeg: str,
    run_fn: Callable[..., str],
) -> list[Path]:
    """One seek per frame: the pre-batch behaviour, and the batch fallback."""
    return [
        extract_frame(
            source, timestamp, dest_dir / frame_filename(scene_id, timestamp), ffmpeg, run_fn
        )
        for timestamp in timestamps
    ]


def extract_scene_frames(
    source: str | Path,
    timestamps: Sequence[float],
    dest_dir: str | Path,
    scene_id: str,
    fps: float | None,
    *,
    ffmpeg: str = "ffmpeg",
    run_fn: Callable[..., str] = ff.check,
) -> list[Path]:
    """One scene's timestamps, one decode pass whenever the pass is trustworthy.

    The per-frame path pays a process launch and a seek-to-time for every
    frame; a scene of six frames is six launches and six decodes of the
    region before the first frame. The batch pass decodes the stream once
    and keeps the frames by index with a single ``select`` filter, which
    writes them in stream order, so the i-th output file is the i-th
    requested timestamp.

    It falls back to one seek per frame when the pass cannot be trusted:

    - no usable fps (index addressing needs a frame rate);
    - two timestamps land on the same frame (the pass would keep one frame
      for two samples);
    - non-ascending timestamps (stream order would not match request order);
    - the pass itself fails (a broken stream fails per frame too, but the
      per-frame error names the timestamp);
    - the pass comes up short (a sample past the last frame is silently
      dropped by the ``select`` filter).

    The fallback reuses :func:`extract_frame`, so a batch that cannot finish
    never loses a frame the old path would have produced.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    ordered = list(timestamps)
    if len(ordered) < 2 or any(a > b for a, b in zip(ordered, ordered[1:], strict=False)):
        return _per_frame(source, ordered, dest, scene_id, ffmpeg, run_fn)

    indices: list[int] | None = None
    if fps is not None and fps > 0:
        try:
            candidates = [frame_index_for(timestamp, fps) for timestamp in ordered]
        except FrameSamplingError:
            candidates = None
        if candidates is not None and len(set(candidates)) == len(candidates):
            indices = candidates
    if indices is None:
        return _per_frame(source, ordered, dest, scene_id, ffmpeg, run_fn)

    batch_dir = dest / ".batch"
    pattern = str(batch_dir / "%05d.jpg")
    # The image2 muxer will not create the output directory; without this the
    # pass dies on the first frame with "Could not open file" and every scene
    # silently falls back to per-frame seeks (T183).
    batch_dir.mkdir(parents=True, exist_ok=True)
    try:
        run_fn(
            ffmpeg,
            [
                "-y",
                "-v",
                "error",
                "-i",
                str(source),
                "-vf",
                f"select={_select_expression(indices)}",
                "-fps_mode",
                "vfr",
                "-q:v",
                "2",
                pattern,
            ],
        )
    except ff.ProcessError as exc:
        _logger.warning(
            "batch frame pass failed for %s (%s); falling back to per-frame", scene_id, exc
        )
        shutil.rmtree(batch_dir, ignore_errors=True)
        return _per_frame(source, ordered, dest, scene_id, ffmpeg, run_fn)

    produced = sorted(batch_dir.glob("*.jpg"))
    if len(produced) > len(ordered):
        shutil.rmtree(batch_dir, ignore_errors=True)
        raise FrameSamplingError(
            f"Batch pass for {scene_id} produced {len(produced)} frames for {len(ordered)} samples"
        )
    for index, frame_file in enumerate(produced):
        os.replace(frame_file, dest / frame_filename(scene_id, ordered[index]))
    shutil.rmtree(batch_dir, ignore_errors=True)
    # A short pass means the trailing samples fell off the end of the stream;
    # the per-frame seek extracts them or names the unextractable timestamp.
    for timestamp in ordered[len(produced) :]:
        extract_frame(source, timestamp, dest / frame_filename(scene_id, timestamp), ffmpeg, run_fn)
    return [dest / frame_filename(scene_id, timestamp) for timestamp in ordered]


def frames_cache_key(
    file_hash: str,
    scenes: list[tuple[str, float, float]],
    cfg: SamplingConfig,
    fps: float | None = None,
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
            "fps": fps,
            "dedupe": cfg.dedupe,
            "dedupe_hamming_threshold": cfg.dedupe_hamming_threshold,
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
    fps: float | None = None,
    ffmpeg: str = "ffmpeg",
    run_fn: Callable[..., str] = ff.check,
    on_progress: ProgressReporter | None = None,
    fingerprint_fn: Callable[[list[Path]], list[int]] | None = None,
) -> SamplingResult:
    """Sample frames for ``(scene_id, start, end)`` spans; skips work on cache hit.

    Reports one step per frame when ``on_progress`` is given. The total is known
    before any extraction starts -- the sum of the per-scene bucket counts -- so
    the fraction is real rather than an estimate.

    ``fps`` (the frame rate of the file being sampled, recorded at ingest)
    lets each scene's frames come from one decode pass; without it the
    sampler keeps one seek per frame.

    ``fingerprint_fn`` replaces the dHash pass for tests. A held shot sampled
    six times is one picture, so beyond a scene's floor of two frames the
    near-duplicates are dropped (T180); a failed fingerprint keeps them all.
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
    key = frames_cache_key(file_hash, scenes, cfg, fps)
    frames_dir = Path(jobs_dir) / job_id / STAGE_NAME
    # Counted up front so the reported fraction is exact, not a guess that
    # drifts when a scene lands in a different bucket than the last one.
    planned = [
        (scene_id, start, end, plan_count(end - start, cfg)) for scene_id, start, end in scenes
    ]
    total_frames = sum(count for _, _, _, count in planned)

    reusable = _reusable_by_scene(cache.lookup_json(key))
    # One deduper for the whole run, in scene order: a resumed run must drop
    # the same frames a fresh run would, so adopted scenes register their
    # recorded hashes into the same state.
    deduper = fingerprint.FrameDeduper(threshold=cfg.dedupe_hamming_threshold)

    frames: list[Frame] = []
    adopted = 0
    extracted = 0
    dropped = 0

    for scene_id, start, end, count in planned:
        # Adopt what a previous run already produced for this scene, even if it
        # lives under an earlier job directory. Re-extracting a frame that is
        # already on disk costs a decode per scene and gains nothing.
        reused = _adopt_scene(reusable.get(scene_id, []), frames_dir, scene_id)
        if reused is not None:
            for frame in reused:
                if frame.dhash:
                    deduper.mark_kept(scene_id, int(frame.dhash, 16))
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

        # One decode pass per scene (T179): the pass falls back to one seek
        # per frame when it cannot be trusted, so this never loses a frame
        # the old behaviour would have produced. It returns the paths in
        # request order, so the timestamps pair by position.
        timestamps = sample_timestamps(start, end, count)
        paths = extract_scene_frames(
            src, timestamps, frames_dir / scene_id, scene_id, fps, ffmpeg=ffmpeg, run_fn=run_fn
        )
        scene_frames = [
            Frame(
                scene_id=scene_id,
                timestamp=timestamp,
                path=path,
                sha256=artifacts.sha256_file(path),
            )
            for timestamp, path in zip(timestamps, paths, strict=True)
        ]
        for _frame in scene_frames:
            extracted += 1
            if on_progress is not None:
                on_progress(
                    WorkProgress(
                        done=extracted,
                        total=total_frames,
                        label=f"frame {extracted}/{total_frames}",
                    )
                )

        # Held shots, dissolves, pans: the samples of a scene can be the same
        # picture (T180). Beyond the scene's floor, a frame within the
        # threshold of a kept one -- in the scene, or at its boundary -- is
        # dropped. A fingerprint failure keeps them all: the frames are
        # valid, only the dedupe evidence is missing.
        if cfg.dedupe:
            hashes = _fingerprint_scene(
                frames_dir / scene_id,
                [f.path for f in scene_frames],
                fingerprint_fn,
                ffmpeg,
                run_fn,
            )
            if hashes is None:
                frames.extend(scene_frames)
            else:
                for frame, frame_hash in zip(scene_frames, hashes, strict=True):
                    if deduper.should_keep(scene_id, frame_hash):
                        deduper.mark_kept(scene_id, frame_hash)
                        frames.append(replace(frame, dhash=f"{frame_hash:016x}"))
                    else:
                        frame.path.unlink(missing_ok=True)
                        dropped += 1
        else:
            frames.extend(scene_frames)

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
            dropped=dropped,
        )
    return SamplingResult(frames=frames, manifest_path=manifest_path, cache_hit=cache_hit)


def _fingerprint_scene(
    scene_dir: Path,
    paths: list[Path],
    fingerprint_fn: Callable[[list[Path]], list[int]] | None,
    ffmpeg: str,
    run_fn: Callable[..., str],
) -> list[int] | None:
    """dHash of a scene's frames, or ``None`` when fingerprinting failed.

    A failed fingerprint must not fail the stage: the frames are valid, only
    the dedupe evidence is missing, so the caller keeps them all and logs the
    gap instead of inventing it away.
    """
    work_dir = scene_dir / ".fingerprint"
    try:
        if fingerprint_fn is not None:
            return fingerprint_fn(list(paths))
        return fingerprint.fingerprint_frames(
            paths, ffmpeg=ffmpeg, run_fn=run_fn, work_dir=work_dir
        )
    except fingerprint.FingerprintError as exc:
        _logger.warning("frame dedupe skipped: %s", exc)
        return None
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _manifest_entries(frames: list[Frame]) -> list[dict[str, object]]:
    """Content-addressed description of every frame produced.

    The digest is the one the frame was created with, not a fresh hash: the
    manifest is written after every scene, so hashing here meant a frame was
    hashed once per scene that followed it.

    The dhash rides along when it exists: it is what a resumed run seeds the
    deduper with, so it drops the same frames a fresh run would.
    """
    entries: list[dict[str, object]] = []
    for frame in frames:
        entry: dict[str, object] = {
            "scene_id": frame.scene_id,
            "timestamp": frame.timestamp,
            "path": str(frame.path),
            "sha256": frame.sha256 or artifacts.sha256_file(frame.path),
        }
        if frame.dhash:
            entry["dhash"] = frame.dhash
        entries.append(entry)
    return entries


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
    entries: list[tuple[float, Path, str, str | None]], frames_dir: Path, scene_id: str
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

    The recorded dhash (when the entry has one) travels with the frame: it is
    what seeds the deduper so a resumed run drops the same frames a fresh run
    would.
    """
    if not entries:
        return None
    frames: list[Frame] = []
    for timestamp, source, expected, dhash in sorted(entries, key=lambda e: e[0]):
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
        # The digest is already known: the entry was recorded with it, and
        # the file was just verified against it.
        frames.append(
            Frame(
                scene_id=scene_id,
                timestamp=timestamp,
                path=dest,
                sha256=expected,
                dhash=dhash or "",
            )
        )
    return frames


def _reusable_by_scene(pointer: object) -> dict[str, list[tuple[float, Path, str, str | None]]]:
    """Group a cache pointer's frames by scene.

    Malformed entries are skipped individually rather than discarding the whole
    pointer: a partially readable manifest should still contribute the scenes it
    can vouch for. An entry without a dhash (pre-dedupe or dedupe off) carries
    ``None``: the deduper simply has no recorded evidence for it.
    """
    grouped: dict[str, list[tuple[float, Path, str, str | None]]] = {}
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
        dhash = entry.get("dhash")
        recorded = dhash if isinstance(dhash, str) else None
        grouped.setdefault(scene_id, []).append((timestamp, path, expected, recorded))
    return grouped
