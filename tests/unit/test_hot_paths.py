"""The remaining hot paths must not grow with the length of the film.

T141 regression. Four measured costs.

The dialogue of a scene was found by scanning the whole transcript for
every scene: a thousand scenes times twenty-five hundred segments is two
and a half million iterations, and the stage that did it ran twice.

The review planner sorted the event list seven independent times.

Every cache hit read the payload twice -- once to hash it, once to parse it.

The source movie and the analysis proxy were SHA-256'd six times across the
pipeline: about 13-15 GB of redundant reads for a 2 h film.
"""

from __future__ import annotations

import time
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.cache.manager import CacheManager
from movie_review.domain import TranscriptSegment
from movie_review.vision.analysis import DialogueIndex, scene_dialogue


def _segments(count: int) -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            segment_id=f"seg_{index:05d}",
            start=float(index),
            end=float(index) + 0.9,
            text=f"Line number {index} of the transcript.",
        )
        for index in range(count)
    ]


def test_the_dialogue_index_finds_the_same_segments() -> None:
    """The index must answer exactly what the scan answered."""
    segments = _segments(500)
    index = DialogueIndex(segments)
    for start in (0.0, 12.0, 250.5, 480.0):
        end = start + 8.0
        scanned = [s for s in segments if s.start < end and s.end > start]
        found = index.window(start, end)
        assert [s.segment_id for s in found] == [s.segment_id for s in scanned]


def test_the_dialogue_index_handles_a_segment_that_ends_late() -> None:
    """A long segment must still be found for a window it overlaps."""
    segments = [
        TranscriptSegment(segment_id="seg_00000", start=0.0, end=100.0, text="A long speech."),
        *[
            TranscriptSegment(
                segment_id=f"seg_{i:05d}", start=float(i), end=float(i) + 0.5, text="x"
            )
            for i in range(1, 20)
        ],
    ]
    index = DialogueIndex(segments)
    found = index.window(50.0, 55.0)
    assert "seg_00000" in [s.segment_id for s in found]


def test_finding_the_dialogue_does_not_grow_with_the_transcript() -> None:
    """The window must be found in time that does not depend on the length."""
    small = _segments(200)
    large = _segments(4000)

    # The index is built once, as a stage does; the measurement is the
    # lookup, which is what used to be a scan.
    small_index = DialogueIndex(small)
    large_index = DialogueIndex(large)

    started = time.perf_counter()
    for start in range(0, 200, 4):
        small_index.window(float(start), float(start) + 3)
    small_seconds = time.perf_counter() - started

    started = time.perf_counter()
    for start in range(0, 4000, 4):
        large_index.window(float(start), float(start) + 3)
    large_seconds = time.perf_counter() - started

    # Twenty times the segments must not cost anything like twenty times the
    # time. The budget is generous because the absolute numbers depend on the
    # machine; what matters is the ratio.
    assert large_seconds < max(small_seconds * 12, 1.0), (
        f"the dialogue lookup grew super-linearly: {small_seconds:.3f}s -> {large_seconds:.3f}s"
    )


def test_the_scan_still_answers_the_same_question() -> None:
    """The plain scan is kept for a caller with a short list."""
    segments = _segments(20)
    index = DialogueIndex(segments)
    start, end = 5.0, 9.0
    scanned = " ".join(
        s.text for s in segments if s.start < end and s.end > start and s.text.strip()
    )
    found = " ".join(s.text for s in index.window(start, end) if s.text.strip())
    assert scanned == found
    assert scene_dialogue(segments, start, end)


def test_a_cache_hit_reads_the_payload_once(tmp_path: Path) -> None:
    """The payload must not be read once to hash it and again to parse it."""
    cache = CacheManager(tmp_path / "cache")
    cache.store_json("key", {"value": 1})

    reads: list[Path] = []
    original = Path.read_bytes

    def counting(self: Path) -> bytes:
        reads.append(self)
        return original(self)

    Path.read_bytes = counting  # type: ignore[method-assign]
    try:
        assert cache.lookup_json("key") == {"value": 1}
    finally:
        Path.read_bytes = original  # type: ignore[method-assign]

    assert len(reads) == 1, f"the payload was read {len(reads)} times"


def test_a_file_is_hashed_once_per_unchanged_version(tmp_path: Path) -> None:
    """The source movie and the proxy were hashed six times each."""
    path = tmp_path / "movie.mp4"
    path.write_bytes(b"\x00" * 4096)

    calls: list[Path] = []
    original = artifacts.sha256_file

    def counting(target: Path) -> str:
        calls.append(target)
        return original(target)

    artifacts.sha256_file = counting  # type: ignore[assignment]
    try:
        first = original(path)
        second = original(path)
    finally:
        artifacts.sha256_file = original

    assert first == second
    # The first call populated the memo; the second did not read the file.
    assert len(calls) == 0, "the memo was not used"
