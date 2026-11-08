"""T180 acceptance: feedback adds frames, but not duplicates.

A boosted static shot must not earn the same picture it already sampled.
The additions are checked against the scene's kept frames (recorded dhashes)
and against each other; a fingerprint failure keeps them all. The feedback
pass must also write its manifest to the same fps-bound cache slot
``sample_movie`` wrote to, or a resumed run would look up the wrong slot.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.manager import CacheManager
from movie_review.domain import Job, Scene, SceneAnalysis
from movie_review.media.feedback import apply_feedback
from movie_review.media.fingerprint import FingerprintError
from movie_review.media.frames import (
    SamplingConfig,
    frames_cache_key,
    sample_movie,
)
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from tests.helpers import (
    _fake_run,
)

FPS = 24.0
SPANS = [("scene_000001", 0.0, 5.0)]


def _hash_of__feedback_dedupe(tag: str) -> int:
    """Digest-derived hash: distinct tags land ~32 bits apart."""
    return int.from_bytes(hashlib.sha256(tag.encode()).digest()[:8], "big")


def _setup__feedback_dedupe(tmp_path: Path) -> tuple[sqlite3.Connection, Path, Path, CacheManager]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    repo.save_scene(conn, "job_1", Scene(scene_id="scene_000001", start=0.0, end=5.0, duration=5.0))
    source = tmp_path / "m.mp4"
    source.write_bytes(b"source-bytes")
    return conn, tmp_path / "jobs", source, CacheManager(tmp_path / "cache")


def _analyses__feedback_dedupe() -> dict[str, tuple[SceneAnalysis, str]]:
    # importance 0.9 boosts a 3-frame scene to 7, i.e. four additions.
    return {"scene_000001": (SceneAnalysis(scene_id="scene_000001", importance=0.9), "hello")}


def _sampled__feedback_dedupe(
    tmp_path: Path, config: SamplingConfig | None = None
) -> tuple[sqlite3.Connection, Path, Path, CacheManager, list[int]]:
    """Base sampling with three distinct kept frames; returns their hashes."""
    conn, jobs_dir, source, cache = _setup__feedback_dedupe(tmp_path)
    kept = [_hash_of__feedback_dedupe(f"kept-{i}") for i in range(3)]

    def _fp(paths: list[Path]) -> list[int]:
        return kept[: len(paths)]

    sample_movie(
        source,
        SPANS,
        job_id="job_1",
        jobs_dir=jobs_dir,
        conn=conn,
        cache=cache,
        config=config,
        fps=FPS,
        run_fn=_fake_run,
        fingerprint_fn=_fp,
    )
    return conn, jobs_dir, source, cache, kept


def test_added_duplicate_frames_are_dropped(tmp_path: Path) -> None:
    conn, jobs_dir, source, cache, kept = _sampled__feedback_dedupe(tmp_path)

    additions = [
        kept[0],
        _hash_of__feedback_dedupe("new-0"),
        kept[2],
        _hash_of__feedback_dedupe("new-1"),
    ]
    seen: list[int] = []

    def _fp(paths: list[Path]) -> list[int]:
        seen.append(len(paths))
        return additions[: len(paths)]

    result = apply_feedback(
        source,
        _analyses__feedback_dedupe(),
        job_id="job_1",
        jobs_dir=jobs_dir,
        conn=conn,
        cache=cache,
        fps=FPS,
        run_fn=_fake_run,
        fingerprint_fn=_fp,
    )

    # Four additions, two of them pictures the scene already kept.
    assert seen == [4]
    assert len(result.added) == 2
    assert [frame.dhash for frame in result.added] == [
        f"{additions[1]:016x}",
        f"{additions[3]:016x}",
    ]
    # The dropped files are gone from disk, the kept ones remain.
    scene_dir = jobs_dir / "job_1" / "frames" / "scene_000001"
    assert len(list(scene_dir.glob("*.jpg"))) == 3 + 2
    # The manifest the resume adopts names five frames (3 kept + 4 added
    # - 2 dropped), with dhashes on every frame.
    key = frames_cache_key(artifacts.sha256_file(source), SPANS, SamplingConfig(), FPS)
    manifest = cache.lookup_json(key)
    assert manifest is not None
    assert len(manifest["frames"]) == 5
    assert all("dhash" in entry for entry in manifest["frames"])
    conn.close()


def test_fingerprint_failure_keeps_every_addition(tmp_path: Path) -> None:
    conn, jobs_dir, source, cache, _kept = _sampled__feedback_dedupe(tmp_path)

    def _boom(paths: list[Path]) -> list[int]:
        raise FingerprintError("frame unreadable")

    result = apply_feedback(
        source,
        _analyses__feedback_dedupe(),
        job_id="job_1",
        jobs_dir=jobs_dir,
        conn=conn,
        cache=cache,
        fps=FPS,
        run_fn=_fake_run,
        fingerprint_fn=_boom,
    )

    # The evidence is missing, the frames are valid: all four stay.
    assert len(result.added) == 4
    assert all(not frame.dhash for frame in result.added)
    scene_dir = jobs_dir / "job_1" / "frames" / "scene_000001"
    assert len(list(scene_dir.glob("*.jpg"))) == 7
    conn.close()


def test_feedback_writes_to_the_fps_bound_cache_slot(tmp_path: Path) -> None:
    no_dedupe = SamplingConfig(dedupe=False)
    conn, jobs_dir, source, cache, _kept = _sampled__feedback_dedupe(tmp_path, config=no_dedupe)

    result = apply_feedback(
        source,
        _analyses__feedback_dedupe(),
        job_id="job_1",
        jobs_dir=jobs_dir,
        conn=conn,
        cache=cache,
        sampling_config=no_dedupe,
        fps=FPS,
        run_fn=_fake_run,
    )
    assert len(result.added) == 4

    # The manifest lands in the slot sample_movie wrote to (fps 24), not in
    # the fps-less slot a resumed run would not look up.
    key_fps = frames_cache_key(artifacts.sha256_file(source), SPANS, no_dedupe, FPS)
    key_none = frames_cache_key(artifacts.sha256_file(source), SPANS, no_dedupe, None)
    stored = cache.lookup_json(key_fps)
    assert stored is not None and len(stored["frames"]) == 7
    assert cache.lookup_json(key_none) is None
    conn.close()


def test_dedupe_off_never_fingerprints_additions(tmp_path: Path) -> None:
    no_dedupe = SamplingConfig(dedupe=False)
    conn, jobs_dir, source, cache, _kept = _sampled__feedback_dedupe(tmp_path, config=no_dedupe)
    calls: list[int] = []

    def _spy(paths: list[Path]) -> list[int]:
        calls.append(len(paths))
        return [_hash_of__feedback_dedupe("x") for _ in paths]

    result = apply_feedback(
        source,
        _analyses__feedback_dedupe(),
        job_id="job_1",
        jobs_dir=jobs_dir,
        conn=conn,
        cache=cache,
        sampling_config=no_dedupe,
        fps=FPS,
        run_fn=_fake_run,
        fingerprint_fn=_spy,
    )

    assert len(result.added) == 4
    assert calls == []
    conn.close()
