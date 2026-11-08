"""Adaptive sampling feedback (T026, README section 12).

After scene analysis, information-dense scenes earn extra frames while
low-information scenes stay at their base budget. Decisions are pure and
deterministic; reasons are recorded for traceability. Signals unavailable
this early (motion scores, cut density) are documented, not fabricated.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.manager import CacheManager
from movie_review.domain import Artifact, Scene, SceneAnalysis
from movie_review.media import ffmpeg as ff
from movie_review.media import fingerprint
from movie_review.media.frames import (
    MANIFEST_FILENAME,
    Frame,
    FrameSamplingError,
    SamplingConfig,
    extract_frame,
    frame_filename,
    frames_cache_key,
    plan_count,
)
from movie_review.media.frames import (
    STAGE_NAME as FRAMES_STAGE,
)
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

MIN_FRAMES = 2
MAX_FRAMES = 24


@dataclass(frozen=True)
class FeedbackConfig:
    """Boost/reduce thresholds (documented defaults, no hard-coding)."""

    important_threshold: float = 0.8
    low_information_threshold: float = 0.3
    important_bonus: int = 4
    action_bonus: int = 2
    new_character_bonus: int = 2


@dataclass(frozen=True)
class SamplingDecision:
    """Adjusted frame budget for one scene with audit reasons."""

    scene_id: str
    base_count: int
    adjusted_count: int
    boosted: bool
    reasons: list[str] = field(default_factory=list)


def decide_feedback(
    scene: Scene,
    analysis: SceneAnalysis,
    dialogue: str,
    known_characters: frozenset[str],
    base_count: int,
    config: FeedbackConfig | None = None,
) -> SamplingDecision:
    """Adjust a scene's frame budget from analysis signals.

    Boosts: high importance, observed actions/events, unseen characters.
    Reduces: low importance with no dialogue, actions, or events (floor 2).
    """
    cfg = config or FeedbackConfig()
    count = base_count
    reasons: list[str] = []
    has_dialogue = bool(dialogue.strip())
    has_action = bool(analysis.actions or analysis.visual_events)

    if analysis.importance >= cfg.important_threshold:
        count += cfg.important_bonus
        reasons.append(f"importance {analysis.importance:.2f} >= {cfg.important_threshold}")
    if has_action:
        count += cfg.action_bonus
        reasons.append("observed actions or visual events")
    new_characters = [c for c in analysis.characters if c not in known_characters]
    if new_characters:
        bonus = min(cfg.new_character_bonus * len(new_characters), cfg.new_character_bonus * 2)
        count += bonus
        reasons.append(f"new characters: {sorted(new_characters)}")
    if not has_dialogue and not has_action and analysis.importance < cfg.low_information_threshold:
        count = max(MIN_FRAMES, count // 2)
        reasons.append("low information: halved to floor")

    adjusted = max(MIN_FRAMES, min(MAX_FRAMES, count))
    return SamplingDecision(
        scene_id=scene.scene_id,
        base_count=base_count,
        adjusted_count=adjusted,
        boosted=adjusted > base_count,
        reasons=reasons,
    )


def additional_timestamps(
    existing: list[float], start: float, end: float, total: int
) -> list[float]:
    """Timestamps to reach ``total`` frames, kept clear of existing samples."""
    if total <= len(existing):
        return []
    span = end - start
    if span <= 0:
        return []
    candidates = [start + span * index / total for index in range(total)]
    min_gap = span / total / 2
    return [
        candidate
        for candidate in candidates
        if all(abs(candidate - taken) >= min_gap for taken in existing)
    ]


@dataclass(frozen=True)
class FeedbackResult:
    """Outcome of one feedback pass."""

    decisions: list[SamplingDecision]
    added: list[Frame]
    manifest_path: Path


def apply_feedback(
    source: str | Path,
    analyses: dict[str, tuple[SceneAnalysis, str]],
    *,
    job_id: str,
    jobs_dir: str | Path,
    conn: sqlite3.Connection,
    cache: CacheManager,
    sampling_config: SamplingConfig | None = None,
    feedback_config: FeedbackConfig | None = None,
    fps: float | None = None,
    ffmpeg: str = "ffmpeg",
    run_fn: Callable[..., str] = ff.check,
    fingerprint_fn: Callable[[list[Path]], list[int]] | None = None,
) -> FeedbackResult:
    """Extract extra frames for boosted scenes; updates manifest and artifact.
    Scene bounds come from persisted scenes, existing frames from the frames
    manifest (a prior ``sample_movie`` run is required). Scenes without an
    analysis entry are skipped. Overwrites the frames cache entry so later
    lookups see appended frames.

    ``fps`` must be the one ``sample_movie`` ran with: the cache key binds it,
    and a different key would leave the feedback's manifest in a slot no one
    looks up.

    An added frame that is a near-duplicate of the scene's kept frames (T180)
    is dropped: a boosted static shot would otherwise get the same picture it
    already sampled. A fingerprint failure keeps the additions.
    """
    cfg = sampling_config or SamplingConfig()
    fcfg = feedback_config or FeedbackConfig()
    src = Path(source)
    if not src.is_file():
        raise FrameSamplingError(f"Input file not found: {src}")
    frames_dir = Path(jobs_dir) / job_id / FRAMES_STAGE
    manifest_path = frames_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise FrameSamplingError("Run frame sampling before feedback")
    try:
        manifest = artifacts.read_json(manifest_path)
        if not isinstance(manifest, dict) or not isinstance(manifest.get("frames"), list):
            raise FrameSamplingError("Frames manifest is corrupt")
    except OSError as exc:
        raise FrameSamplingError(f"Cannot read frames manifest: {exc}") from exc

    scenes = repo.list_scenes(conn, job_id)
    existing: dict[str, list[float]] = {}
    existing_hashes: dict[str, list[int]] = {}
    existing_paths: dict[str, list[Path]] = {}
    for entry in manifest["frames"]:
        scene_id = str(entry["scene_id"])
        existing.setdefault(scene_id, []).append(float(entry["timestamp"]))
        existing_paths.setdefault(scene_id, []).append(Path(str(entry["path"])))
        dhash = entry.get("dhash")
        if isinstance(dhash, str) and dhash:
            existing_hashes.setdefault(scene_id, []).append(int(dhash, 16))

    known: set[str] = set()
    decisions: list[SamplingDecision] = []
    added: list[Frame] = []
    dropped = 0
    for scene in scenes:
        item = analyses.get(scene.scene_id)
        if item is None:
            continue
        analysis, dialogue = item
        base_count = plan_count(scene.end - scene.start, cfg)
        decision = decide_feedback(scene, analysis, dialogue, frozenset(known), base_count, fcfg)
        decisions.append(decision)
        known.update(analysis.characters)
        extra = additional_timestamps(
            sorted(existing.get(scene.scene_id, [])),
            scene.start,
            scene.end,
            decision.adjusted_count,
        )
        scene_dir = frames_dir / scene.scene_id
        scene_added: list[Frame] = []
        for timestamp in extra:
            dest = scene_dir / frame_filename(scene.scene_id, timestamp)
            extract_frame(src, timestamp, dest, ffmpeg, run_fn)
            scene_added.append(Frame(scene_id=scene.scene_id, timestamp=timestamp, path=dest))
        if cfg.dedupe and scene_added:
            scene_added, n_dropped = _dedupe_additions(
                scene.scene_id,
                scene_added,
                existing_hashes.get(scene.scene_id, []),
                existing_paths.get(scene.scene_id, []),
                cfg.dedupe_hamming_threshold,
                fingerprint_fn,
                ffmpeg,
                run_fn,
                scene_dir,
            )
            dropped += n_dropped
        added.extend(scene_added)

    if added:
        manifest["frames"].extend(
            {
                "scene_id": frame.scene_id,
                "timestamp": frame.timestamp,
                "path": str(frame.path),
                "sha256": artifacts.sha256_file(frame.path),
                **({"dhash": frame.dhash} if frame.dhash else {}),
            }
            for frame in added
        )
        output_hash = artifacts.write_json(manifest_path, manifest)
        file_hash = artifacts.sha256_file(src)
        # The same key sample_movie wrote to, fps and all: this manifest is
        # the one a resumed run adopts.
        key = frames_cache_key(
            file_hash,
            [(scene.scene_id, scene.start, scene.end) for scene in scenes],
            cfg,
            fps,
        )
        cache.store_json(key, manifest)
        repo.save_artifact(
            conn,
            Artifact(
                artifact_id=f"{job_id}-frames",
                job_id=job_id,
                stage=FRAMES_STAGE,
                relative_path=artifacts.relative_artifact_path(jobs_dir, job_id, manifest_path),
                input_hash=file_hash,
                output_hash=output_hash,
            ),
        )
    with ulog.logging_context(job_id=job_id, stage=FRAMES_STAGE):
        ulog.log_event(
            _logger,
            event="feedback.applied",
            status="ok",
            added=len(added),
            dropped=dropped,
        )
    return FeedbackResult(decisions=decisions, added=added, manifest_path=manifest_path)


def _dedupe_additions(
    scene_id: str,
    scene_added: list[Frame],
    existing_hashes: list[int],
    existing_paths: list[Path],
    threshold: int,
    fingerprint_fn: Callable[[list[Path]], list[int]] | None,
    ffmpeg: str,
    run_fn: Callable[..., str],
    scene_dir: Path,
) -> tuple[list[Frame], int]:
    """Drop added frames that duplicate the scene's kept frames.

    The additions are checked against the scene's existing kept frames (their
    recorded dhashes, re-fingerprinted when a frame lacks one) and against
    each other in extraction order. The scene's floor was met by the base
    samples, so every addition is checked -- there is no floor to protect
    here. A fingerprint failure keeps all the additions and logs it.
    """
    work_dir = scene_dir / ".fingerprint"
    try:
        if fingerprint_fn is not None:
            hash_of = fingerprint_fn
        else:

            def hash_of(paths: list[Path]) -> list[int]:
                return fingerprint.fingerprint_frames(
                    paths, ffmpeg=ffmpeg, run_fn=run_fn, work_dir=work_dir
                )

        if len(existing_hashes) < len(existing_paths):
            # Some kept frame lacks a recorded dhash: fingerprint the scene's
            # kept files once so the check has every side of the comparison.
            existing_hashes = hash_of(list(existing_paths))
        added_hashes = hash_of([frame.path for frame in scene_added])
    except fingerprint.FingerprintError as exc:
        _logger.warning("feedback dedupe skipped for %s: %s", scene_id, exc)
        return scene_added, 0
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    kept_hashes = list(existing_hashes)
    kept: list[Frame] = []
    dropped = 0
    for frame, frame_hash in zip(scene_added, added_hashes, strict=True):
        if any(fingerprint.hamming_distance(frame_hash, h) <= threshold for h in kept_hashes):
            frame.path.unlink(missing_ok=True)
            dropped += 1
        else:
            kept_hashes.append(frame_hash)
            kept.append(replace(frame, dhash=f"{frame_hash:016x}"))
    return kept, dropped
