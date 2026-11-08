"""T180 acceptance: sample_movie drops near-duplicate frames, deterministically.

The fake ``run_fn`` emulates the batch pass (content by frame index) and the
dHash pass (a digest of each frame's bytes, so identical frames hash
identically and distinct frames hash far).
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.manager import CacheManager
from movie_review.domain import Job
from movie_review.media.fingerprint import FingerprintError
from movie_review.media.frames import (
    SamplingConfig,
    frames_cache_key,
    sample_movie,
)
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect

FPS = 24.0


def _is_batch_call__frames_dedupe(args: list[str]) -> bool:
    return any(arg.startswith("select=") for arg in args)


def _fake_run__frames_dedupe(
    recorded: list[list[str]],
    content_by_index: dict[int, bytes] | None = None,
    static_content: bytes | None = None,
) -> Callable[..., str]:
    def _run(binary: str, args: list[str]) -> str:
        recorded.append(list(args))
        if "rawvideo" in args:
            list_file = Path(args[args.index("-i") + 1])
            lines = list_file.read_text().strip().splitlines()
            blocks: list[bytes] = []
            for line in lines:
                frame = Path(line.split("'")[1])
                digest = hashlib.sha256(frame.read_bytes()).digest()
                blocks.append((digest * 3)[:72])
            Path(args[-1]).write_bytes(b"".join(blocks))
            return ""
        vf = args[args.index("-vf") + 1]
        indices = [int(match) for match in re.findall(r"eq\(n\\,(?P<i>\d+)\)", vf)]
        pattern = Path(args[-1])
        pattern.parent.mkdir(parents=True, exist_ok=True)
        for position, index in enumerate(indices, start=1):
            if static_content is not None:
                content = static_content
            else:
                content = (content_by_index or {}).get(index, f"frame-{index}".encode())
            Path(str(pattern) % position).write_bytes(content)
        return ""

    return _run


@dataclass
class Harness:
    conn: sqlite3.Connection
    jobs_dir: Path
    cache: CacheManager
    source: Path

    def sample(
        self,
        scenes: list[tuple[str, float, float]] | None = None,
        run_fn: Callable[..., str] | None = None,
        config: SamplingConfig | None = None,
        fingerprint_fn: Callable[[list[Path]], list[int]] | None = None,
    ):
        return sample_movie(
            self.source,
            scenes or [("scene_000001", 0.0, 10.0)],
            job_id="job_1",
            jobs_dir=self.jobs_dir,
            conn=self.conn,
            cache=self.cache,
            fps=FPS,
            config=config,
            run_fn=_fake_run__frames_dedupe([]) if run_fn is None else run_fn,
            fingerprint_fn=fingerprint_fn,
        )


def _harness(tmp_path: Path) -> Harness:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    source = tmp_path / "m.mp4"
    source.write_bytes(b"source-bytes")
    return Harness(
        conn=conn,
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        source=source,
    )


def test_static_scene_keeps_the_floor_and_drops_the_rest(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    recorded: list[list[str]] = []
    run_fn = _fake_run__frames_dedupe(recorded, static_content=b"held-shot")

    result = harness.sample(run_fn=run_fn)

    # Six samples of one held shot: the floor of two is kept, four dropped.
    assert len(result.frames) == 2
    assert [f.timestamp for f in result.frames] == [0.0, 5.0 / 3.0]
    for frame in result.frames:
        assert frame.path.is_file()
    scene_dir = harness.jobs_dir / "job_1" / "frames" / "scene_000001"
    assert len(list(scene_dir.glob("*.jpg"))) == 2
    # The dHash ran as one pass for the scene's six frames.
    fingerprint_calls = [args for args in recorded if "rawvideo" in args]
    assert len(fingerprint_calls) == 1
    # The manifest records the dhash of every kept frame.
    key = frames_cache_key(
        artifacts.sha256_file(harness.source),
        [("scene_000001", 0.0, 10.0)],
        SamplingConfig(),
        FPS,
    )
    manifest = harness.cache.lookup_json(key)
    assert manifest is not None
    assert all("dhash" in entry for entry in manifest["frames"])
    assert len(manifest["frames"]) == 2


def test_dynamic_scene_keeps_every_frame(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    recorded: list[list[str]] = []
    run_fn = _fake_run__frames_dedupe(recorded)  # distinct content per frame index

    result = harness.sample(run_fn=run_fn)

    assert len(result.frames) == 6
    assert len({f.dhash for f in result.frames}) == 6
    assert all(f.dhash for f in result.frames)


def test_boundary_duplicate_beyond_the_floor_is_dropped(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    recorded: list[list[str]] = []
    # Scene 1 (indexes 0..200) holds on picture A. Scene 2 (240..440) shows
    # C, D, then returns to A for its four remaining samples.
    content_by_index: dict[int, bytes] = {
        **{index: b"A" for index in (0, 40, 80, 120, 160, 200)},
        240: b"C",
        280: b"D",
        **{index: b"A" for index in (320, 360, 400, 440)},
    }
    run_fn = _fake_run__frames_dedupe(recorded, content_by_index)

    result = harness.sample(
        [("scene_000001", 0.0, 10.0), ("scene_000002", 10.0, 20.0)], run_fn=run_fn
    )

    scene_1 = [f for f in result.frames if f.scene_id == "scene_000001"]
    scene_2 = [f for f in result.frames if f.scene_id == "scene_000002"]
    # Scene 1: six A's collapse to the floor of two.
    assert len(scene_1) == 2
    # Scene 2: C and D (the floor) are kept; the return to A matches the
    # picture scene 1 ended on, so beyond the floor it is dropped.
    assert len(scene_2) == 2
    assert [f.timestamp for f in scene_2] == [10.0, 10.0 + 10.0 / 6.0]
    assert len(result.frames) == 4


def test_cache_key_binds_the_dedupe_switch_and_threshold() -> None:
    # Frames sampled with dedupe on are not the frames sampled with it off
    # (or at a different threshold), so the cache must not adopt them.
    scenes = [("scene_000001", 0.0, 10.0)]
    a = frames_cache_key("h", scenes, SamplingConfig(), FPS)
    b = frames_cache_key("h", scenes, SamplingConfig(dedupe=False), FPS)
    c = frames_cache_key("h", scenes, SamplingConfig(dedupe_hamming_threshold=10), FPS)
    assert a != b
    assert a != c


def test_dedupe_disabled_keeps_every_frame(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    recorded: list[list[str]] = []
    run_fn = _fake_run__frames_dedupe(recorded, static_content=b"held-shot")

    result = harness.sample(run_fn=run_fn, config=SamplingConfig(dedupe=False))

    assert len(result.frames) == 6
    assert all(not f.dhash for f in result.frames)
    # No fingerprint pass ran at all.
    assert not any("rawvideo" in args for args in recorded)


def test_fingerprint_failure_keeps_every_frame(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    recorded: list[list[str]] = []
    run_fn = _fake_run__frames_dedupe(recorded, static_content=b"held-shot")

    def _broken(paths: list[Path]) -> list[int]:
        raise FingerprintError("frame unreadable")

    result = harness.sample(run_fn=run_fn, fingerprint_fn=_broken)

    assert len(result.frames) == 6
    assert all(not f.dhash for f in result.frames)


def test_resumed_run_keeps_the_same_frames_a_fresh_run_keeps(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    scenes = [("scene_000001", 0.0, 10.0), ("scene_000002", 10.0, 20.0)]
    fresh_calls: list[list[str]] = []
    fresh = harness.sample(
        scenes, run_fn=_fake_run__frames_dedupe(fresh_calls, static_content=b"held-shot")
    )
    assert len(fresh.frames) == 4  # 2 + 2, both scenes holding on the same shot

    # A run that completed only scene 1, then died: the cache pointer names
    # only scene 1's survivors. The on-disk manifest is rewritten in full on
    # the next persist, so only the pointer is trimmed here.
    key = frames_cache_key(artifacts.sha256_file(harness.source), scenes, SamplingConfig(), FPS)
    partial = harness.cache.lookup_json(key)
    assert partial is not None
    partial["frames"] = [e for e in partial["frames"] if e["scene_id"] == "scene_000001"]
    harness.cache.store_json(key, partial)

    resumed_calls: list[list[str]] = []
    resumed = harness.sample(
        scenes, run_fn=_fake_run__frames_dedupe(resumed_calls, static_content=b"held-shot")
    )

    # Scene 1 adopted without re-extraction; only scene 2 ran the pass.
    resumed_batch = [args for args in resumed_calls if _is_batch_call__frames_dedupe(args)]
    assert len(resumed_batch) == 1
    # The final frame set is the same as the fresh run's, dhashes included:
    # the deduper was seeded from scene 1's recorded hashes.
    assert resumed.cache_hit is False
    assert [f.timestamp for f in resumed.frames] == [f.timestamp for f in fresh.frames]
    assert [f.dhash for f in resumed.frames] == [f.dhash for f in fresh.frames]
