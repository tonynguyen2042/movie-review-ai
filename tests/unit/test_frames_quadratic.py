"""A frame must be hashed once, not once per scene that follows it.

T133 regression. The frames manifest was written after every scene, and
building it re-hashed every frame it listed. A frame was therefore hashed
once per scene that followed it -- quadratic in the number of frames.

Measured on the old code: 300 frames / 100 scenes 7.0 s, 600 frames / 200
scenes 19.9 s. A 2 h film has roughly 3500 frames, so the stage spent 12-45
minutes writing the manifest before the first VLM call.
"""

from __future__ import annotations

import time
from pathlib import Path

from movie_review.media.frames import Frame, _manifest_entries


def _frames(tmp_path: Path, count: int) -> list[Frame]:
    """Frames on disk, with the digest each one carries."""
    from movie_review.artifacts import manager as artifacts

    tmp_path.mkdir(parents=True, exist_ok=True)
    frames: list[Frame] = []
    for index in range(count):
        path = tmp_path / f"frame_{index:05d}.jpg"
        path.write_bytes(b"\x00" * 4096)
        frames.append(
            Frame(
                scene_id=f"scene_{index // 3:06d}",
                timestamp=float(index),
                path=path,
                sha256=artifacts.sha256_file(path),
            )
        )
    return frames


def test_building_the_manifest_does_not_rehash(tmp_path: Path, monkeypatch: object) -> None:
    """The manifest must use the digest the frame already carries."""
    from movie_review.artifacts import manager as artifacts

    frames = _frames(tmp_path, 30)
    calls: list[Path] = []
    real = artifacts.sha256_file

    def counting(path: Path) -> str:
        calls.append(path)
        return real(path)

    monkeypatch.setattr(artifacts, "sha256_file", counting)  # type: ignore[attr-defined]
    entries = _manifest_entries(frames)

    assert len(entries) == 30
    assert calls == [], f"the manifest re-hashed {len(calls)} frames"


def test_the_manifest_still_records_the_right_digest(tmp_path: Path) -> None:
    """The digest must be the file's, not a placeholder."""
    from movie_review.artifacts import manager as artifacts

    frames = _frames(tmp_path, 3)
    entries = _manifest_entries(frames)
    for frame, entry in zip(frames, entries, strict=True):
        assert entry["sha256"] == artifacts.sha256_file(frame.path)


def test_a_frame_without_a_digest_is_still_hashed(tmp_path: Path) -> None:
    """A frame built elsewhere may not carry one; the manifest must cope."""
    from movie_review.artifacts import manager as artifacts

    path = tmp_path / "frame.jpg"
    path.write_bytes(b"\x00" * 128)
    frame = Frame(scene_id="scene_000001", timestamp=1.0, path=path)
    entries = _manifest_entries([frame])
    assert entries[0]["sha256"] == artifacts.sha256_file(path)


def test_building_a_large_manifest_is_not_quadratic(tmp_path: Path) -> None:
    """The cost of a manifest must scale with the frames, not with the squares.

    The old code re-hashed every frame it listed, and the manifest was
    written after every scene, so the stage's hashing cost grew with the
    square of the frame count.
    """
    small = _frames(tmp_path / "small", 300)
    large = _frames(tmp_path / "large", 1200)

    started = time.perf_counter()
    _manifest_entries(small)
    small_seconds = time.perf_counter() - started

    started = time.perf_counter()
    _manifest_entries(large)
    large_seconds = time.perf_counter() - started

    # Four times the frames must not cost anything like sixteen times the
    # time. The budget is generous because the absolute numbers depend on
    # the disk; what matters is the ratio.
    assert large_seconds < max(small_seconds * 8, 0.5), (
        f"the manifest cost grew super-linearly: {small_seconds:.3f}s -> "
        f"{large_seconds:.3f}s for 4x the frames"
    )
