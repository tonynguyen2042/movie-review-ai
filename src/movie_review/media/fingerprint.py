"""Perceptual frame fingerprints: 64-bit difference hashes of tiny renders.

Evenly spaced timestamps do not know a scene holds still: a static shot
sampled six times produces six near-identical frames, and the VLM is then
asked to read the same picture six times. A difference hash (dHash) reduces
a frame to the 64 bits of its coarse structure -- horizontally adjacent
pixels compared in a 9x8 grayscale render. Near-identical frames hash close
in Hamming distance; different frames hash far.

No image library is needed: one FFmpeg concat pass renders every frame of a
scene to raw 9x8 grayscale bytes in a single launch, and the bits are read
off the bytes. The cost is one process launch per scene, not one per frame,
and nothing about a movie frame leaves the machine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from movie_review.media import ffmpeg as ff

_logger = logging.getLogger(__name__)

#: dHash geometry: 9 wide by 8 tall gives 8 comparisons per row, 64 bits.
HASH_WIDTH = 9
HASH_HEIGHT = 8
HASH_BITS = (HASH_WIDTH - 1) * HASH_HEIGHT
_RAW_BYTES = HASH_WIDTH * HASH_HEIGHT

#: A frame is a near-duplicate when its hash differs by at most this many
#: bits. Small enough that a pan or a lighting shift keeps both frames; large
#: enough that a held shot collapses to the first two samples.
DEFAULT_HAMMING_THRESHOLD = 5


class FingerprintError(Exception):
    """Fingerprinting failed in a classified way."""


def difference_hash(pixels: bytes, width: int = HASH_WIDTH, height: int = HASH_HEIGHT) -> int:
    """Bits of a grayscale image: bit i is 1 when the left pixel is darker.

    ``pixels`` is row-major, ``width * height`` bytes, 0..255. The result is
    independent of absolute brightness -- only the direction of each
    horizontal edge is recorded -- which is what makes two renderings of the
    same picture land close together.
    """
    if len(pixels) != width * height:
        raise ValueError(f"Expected {width * height} bytes, got {len(pixels)}")
    bits = 0
    for row in range(height):
        base = row * width
        for col in range(width - 1):
            bits = (bits << 1) | (1 if pixels[base + col] < pixels[base + col + 1] else 0)
    return bits


def hamming_distance(a: int, b: int) -> int:
    """The number of bits in which two hashes differ."""
    return (a ^ b).bit_count()


def fingerprint_frames(
    paths: Sequence[str | Path],
    *,
    ffmpeg: str = "ffmpeg",
    run_fn: Callable[..., str] = ff.check,
    work_dir: str | Path,
) -> list[int]:
    """dHash of every frame, one FFmpeg pass for the whole list.

    A concat demuxer reads the frames in order and one ``scale=9:8`` filter
    renders each to raw grayscale; the i-th 72-byte block of the output is
    the i-th frame. Raises :class:`FingerprintError` when a frame cannot be
    read or the pass comes up short of the expected size.
    """
    frames = [Path(path) for path in paths]
    if not frames:
        return []
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    list_file = work / "list.txt"
    raw_file = work / "hashes.raw"
    list_file.write_text(
        "".join(f"file '{frame.resolve()}'\n" for frame in frames), encoding="utf-8"
    )
    try:
        run_fn(
            ffmpeg,
            [
                "-y",
                "-v",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-vf",
                f"scale={HASH_WIDTH}:{HASH_HEIGHT}:flags=area",
                "-pix_fmt",
                "gray",
                "-f",
                "rawvideo",
                str(raw_file),
            ],
        )
    except ff.ProcessError as exc:
        raise FingerprintError(f"Cannot fingerprint {len(frames)} frames: {exc}") from exc
    if not raw_file.is_file():
        raise FingerprintError("Fingerprint pass produced no output")
    data = raw_file.read_bytes()
    if len(data) != len(frames) * _RAW_BYTES:
        raise FingerprintError(
            f"Fingerprint pass produced {len(data)} bytes for {len(frames)} frames "
            f"(expected {len(frames) * _RAW_BYTES}); a frame could not be read"
        )
    return [
        difference_hash(data[index * _RAW_BYTES : (index + 1) * _RAW_BYTES])
        for index in range(len(frames))
    ]


class FrameDeduper:
    """Greedy near-duplicate filter over frames in arrival (time) order.

    The first ``min_per_scene`` frames of a scene are always kept: the VLM
    needs material even when the shot holds perfectly still. Beyond the
    floor a frame is dropped when it is within ``threshold`` bits of any
    frame already kept in its scene, or -- when ``boundary`` is on -- of the
    last frame kept before the scene began (the picture two scenes share
    across a dissolve). The first frame of a duplicate run is the survivor.
    """

    def __init__(self, threshold: int = DEFAULT_HAMMING_THRESHOLD, min_per_scene: int = 2) -> None:
        if threshold < 0:
            raise ValueError(f"threshold must be >= 0, got {threshold}")
        if min_per_scene < 1:
            raise ValueError(f"min_per_scene must be >= 1, got {min_per_scene}")
        self._threshold = threshold
        self._min_per_scene = min_per_scene
        self._scene_kept: dict[str, list[int]] = {}
        self._scene_order: list[str] = []
        self._scene_last_kept: dict[str, int] = {}
        self._boundary = True

    def _note_scene(self, scene_id: str) -> None:
        if scene_id not in self._scene_order:
            self._scene_order.append(scene_id)

    def _previous_scene_last_kept(self, scene_id: str) -> int | None:
        """The last frame kept in the scene before this one, if any.

        The boundary reference is the previous *scene's* last kept frame, not
        the most recent kept frame overall: once this scene keeps its floor
        frames, the most recent kept frame is this scene's own, and the
        picture shared across the cut would no longer be reachable.
        """
        if scene_id not in self._scene_order:
            return None
        position = self._scene_order.index(scene_id)
        if position == 0:
            return None
        return self._scene_last_kept.get(self._scene_order[position - 1])

    def seed_scene(self, scene_id: str, hashes: Sequence[int]) -> None:
        """Record frames a previous pass already kept for this scene.

        Used when adopted frames carry their recorded hashes: a resumed run
        must drop the same frames a fresh run would, or the manifest would
        differ between a fresh run and a resume. Seeds in arrival order and,
        when it has the scene's final frame, also sets the boundary reference
        for the scene that follows.
        """
        self._note_scene(scene_id)
        self._scene_kept.setdefault(scene_id, []).extend(hashes)
        if hashes:
            self._scene_last_kept[scene_id] = hashes[-1]

    def should_keep(self, scene_id: str, frame_hash: int) -> bool:
        """True when the frame is not a near-duplicate of what is kept."""
        self._note_scene(scene_id)
        kept = self._scene_kept.get(scene_id, [])
        if len(kept) < self._min_per_scene:
            return True
        if any(hamming_distance(frame_hash, h) <= self._threshold for h in kept):
            return False
        if not self._boundary:
            return True
        previous_last = self._previous_scene_last_kept(scene_id)
        if previous_last is None:
            return True
        return hamming_distance(frame_hash, previous_last) > self._threshold

    def mark_kept(self, scene_id: str, frame_hash: int) -> None:
        """Record a kept frame as the scene's latest kept frame.

        A dropped frame is never recorded: it is not evidence for later
        frames, and the first frame of a duplicate run is the survivor.
        """
        self._note_scene(scene_id)
        self._scene_kept.setdefault(scene_id, []).append(frame_hash)
        self._scene_last_kept[scene_id] = frame_hash

    @property
    def boundary(self) -> bool:
        return self._boundary

    @boundary.setter
    def boundary(self, value: bool) -> None:
        self._boundary = value
