"""T180 acceptance: dHash fingerprints and the near-duplicate filter.

Pure functions are tested on synthetic bytes; the FFmpeg concat pass is
tested both against a fake ``run_fn`` (counting invocations) and a real
encode (near-identical frames hash close, different frames hash far).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from movie_review.media import ffmpeg as ff
from movie_review.media.fingerprint import (
    HASH_BITS,
    FingerprintError,
    FrameDeduper,
    difference_hash,
    fingerprint_frames,
    hamming_distance,
)


def _pixels(value: int) -> bytes:
    return bytes([value] * 9 * 8)


def _patterns() -> dict[str, int]:
    """Four canonical pictures, pairwise at least 32 bits apart."""
    return {
        "alt": difference_hash(bytes([10, 20] * 36)),  # 101010...
        "alt_flip": difference_hash(bytes([20, 10] * 36)),  # 010101...
        "ramp_up": difference_hash(bytes((i * 3) % 256 for i in range(72))),  # 111...
        "ramp_down": difference_hash(bytes((255 - i * 3) % 256 for i in range(72))),  # 000...
    }


def test_difference_hash_is_deterministic_and_64_bit() -> None:
    pixels = bytes((i * 7) % 256 for i in range(72))
    a = difference_hash(pixels)
    b = difference_hash(pixels)
    assert a == b
    assert 0 <= a < 2**HASH_BITS


def test_difference_hash_ignores_brightness() -> None:
    """Only edge direction is recorded: a shifted ramp hashes identically."""
    ramp = bytes((i * 4) % 256 for i in range(72))
    shifted = bytes((i * 4 + 3) % 256 for i in range(72))
    assert difference_hash(ramp) == difference_hash(shifted)


def test_difference_hash_sees_structure() -> None:
    patterns = _patterns()
    assert hamming_distance(patterns["alt"], patterns["alt_flip"]) == 64
    assert hamming_distance(patterns["ramp_up"], patterns["ramp_down"]) == 64
    assert hamming_distance(patterns["alt"], patterns["ramp_up"]) == 32
    # A flat picture has no edges at all.
    assert difference_hash(_pixels(128)) == 0


def test_difference_hash_rejects_wrong_size() -> None:
    with pytest.raises(ValueError, match="Expected 72 bytes"):
        difference_hash(b"short")


def test_hamming_distance() -> None:
    assert hamming_distance(0, 0) == 0
    assert hamming_distance(0b1010, 0b0101) == 4
    assert hamming_distance(0, 2**64 - 1) == 64


def _fake_fingerprint_run(recorded: list[list[str]]) -> Callable[..., str]:
    """Emulates the concat pass: one 72-byte block per listed frame."""

    def _run(binary: str, args: list[str]) -> str:
        recorded.append(list(args))
        list_file = Path(args[args.index("-i") + 1])
        lines = list_file.read_text().strip().splitlines()
        blocks: list[bytes] = []
        for line in lines:
            frame = Path(line.split("'")[1])
            digest = hashlib.sha256(frame.read_bytes()).digest()
            blocks.append((digest * 3)[:72])
        Path(args[-1]).write_bytes(b"".join(blocks))
        return ""

    return _run


def test_fingerprint_is_one_pass_for_many_frames(tmp_path: Path) -> None:
    recorded: list[list[str]] = []
    frames = []
    for i in range(5):
        path = tmp_path / f"f{i}.jpg"
        path.write_bytes(f"content-{i}".encode())
        frames.append(path)

    hashes = fingerprint_frames(
        frames, run_fn=_fake_fingerprint_run(recorded), work_dir=tmp_path / "w"
    )

    assert len(recorded) == 1  # one pass, not one per frame
    assert "concat" in recorded[0]
    assert len(hashes) == 5
    assert len(set(hashes)) == 5  # different content hashes far apart
    # The list names the frames in order.
    list_text = (tmp_path / "w" / "list.txt").read_text()
    assert list_text.index("f0.jpg") < list_text.index("f4.jpg")


def test_fingerprint_of_identical_frames_is_identical(tmp_path: Path) -> None:
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    a.write_bytes(b"same-picture")
    b.write_bytes(b"same-picture")

    hashes = fingerprint_frames([a, b], run_fn=_fake_fingerprint_run([]), work_dir=tmp_path / "w")

    assert hamming_distance(hashes[0], hashes[1]) == 0


def test_fingerprint_short_output_is_an_error(tmp_path: Path) -> None:
    frame = tmp_path / "a.jpg"
    frame.write_bytes(b"pic")

    def _short(binary: str, args: list[str]) -> str:
        Path(args[-1]).write_bytes(b"tiny")  # one frame short
        return ""

    with pytest.raises(FingerprintError, match="could not be read"):
        fingerprint_frames([frame], run_fn=_short, work_dir=tmp_path / "w")


def test_fingerprint_ffmpeg_failure_is_classified(tmp_path: Path) -> None:
    frame = tmp_path / "a.jpg"
    frame.write_bytes(b"pic")

    def _boom(binary: str, args: list[str]) -> str:
        raise ff.ProcessError(binary, args, "decode failed")

    with pytest.raises(FingerprintError, match="Cannot fingerprint"):
        fingerprint_frames([frame], run_fn=_boom, work_dir=tmp_path / "w")


def test_fingerprint_empty_input() -> None:
    assert (
        fingerprint_frames([], run_fn=_fake_fingerprint_run([]), work_dir=Path("/nonexistent"))
        == []
    )


def test_deduper_floor_keeps_two_of_a_static_scene() -> None:
    deduper = FrameDeduper(threshold=5)
    static = _patterns()["alt"]
    kept = 0
    for _ in range(6):
        if deduper.should_keep("s1", static):
            deduper.mark_kept("s1", static)
            kept += 1
    assert kept == 2


def test_deduper_keeps_distinct_frames() -> None:
    deduper = FrameDeduper(threshold=5)
    for h in _patterns().values():
        assert deduper.should_keep("s1", h)
        deduper.mark_kept("s1", h)


def test_deduper_boundary_drops_a_shared_frame_beyond_the_floor() -> None:
    p = _patterns()
    deduper = FrameDeduper(threshold=5)
    shared, first, second = p["alt"], p["alt_flip"], p["ramp_up"]

    # Scene 1 ends on the shared picture.
    deduper.mark_kept("s1", second)
    deduper.mark_kept("s1", shared)
    # Scene 2's floor frames are kept unconditionally.
    assert deduper.should_keep("s2", first)
    deduper.mark_kept("s2", first)
    assert deduper.should_keep("s2", second)
    deduper.mark_kept("s2", second)
    # Beyond the floor, the shared picture is a boundary duplicate: it
    # matches neither of scene 2's kept frames, only scene 1's last.
    assert not deduper.should_keep("s2", shared)


def test_deduper_boundary_ignores_older_scenes() -> None:
    p = _patterns()
    deduper = FrameDeduper(threshold=5)
    old, prev, fresh = p["alt"], p["alt_flip"], p["ramp_up"]

    deduper.mark_kept("s1", old)
    deduper.mark_kept("s2", prev)
    # Scene 3 is compared with scene 2's last kept, not scene 1's: a frame
    # that only duplicates s1 is not a boundary duplicate of s3.
    deduper.mark_kept("s3", fresh)
    deduper.mark_kept("s3", p["ramp_down"])
    assert deduper.should_keep("s3", old)


def test_deduper_dropped_frames_are_not_evidence() -> None:
    p = _patterns()
    deduper = FrameDeduper(threshold=5, min_per_scene=1)
    a, b = p["alt"], p["alt_flip"]
    deduper.mark_kept("s1", a)
    # a is within threshold of kept a -> dropped, and must not advance state.
    assert not deduper.should_keep("s1", a)
    # b is still judged against the kept frame only.
    assert deduper.should_keep("s1", b)


def test_deduper_validation() -> None:
    with pytest.raises(ValueError):
        FrameDeduper(threshold=-1)
    with pytest.raises(ValueError):
        FrameDeduper(min_per_scene=0)


@pytest.mark.ffmpeg
def test_real_frames_near_identical_hash_close_and_different_hash_far(tmp_path: Path) -> None:
    """A frame extracted twice hashes identically; another source hashes far.

    Two testsrc frames half a second apart still hash within the threshold:
    at the 9x8 the dHash sees, testsrc's motion is below the resolution.
    That is the point -- the filter is for "the same picture", not "the
    same second".
    """
    clip = tmp_path / "clip.mp4"
    ff.check(
        "ffmpeg",
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=24:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(clip),
        ],
    )
    first = tmp_path / "first.jpg"
    again = tmp_path / "again.jpg"
    for path in (first, again):
        ff.check(
            "ffmpeg",
            [
                "-y",
                "-i",
                str(clip),
                "-vf",
                "select=eq(n\\,0)",
                "-frames:v",
                "1",
                "-pix_fmt",
                "yuvj420p",
                "-q:v",
                "2",
                str(path),
            ],
        )
    bars = tmp_path / "bars.jpg"
    ff.check(
        "ffmpeg",
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "smptebars=size=320x240:rate=24:duration=1",
            "-frames:v",
            "1",
            "-pix_fmt",
            "yuvj420p",
            "-q:v",
            "2",
            str(bars),
        ],
    )

    hashes = fingerprint_frames([first, again, bars], work_dir=tmp_path / "w")
    assert hamming_distance(hashes[0], hashes[1]) <= 5
    assert hamming_distance(hashes[0], hashes[2]) > 5
