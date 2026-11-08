"""T179 acceptance: one decode pass per scene, with a trustworthy fallback.

The fake ``run_fn`` emulates both ffmpeg shapes the sampler can produce: the
batch pass (``-vf select=eq(n\\,IDX)+...`` writing numbered files in stream
order) and the per-frame seek (``-ss T ... OUT``). File contents are keyed by
frame index, so a test can assert which frame landed on which filename.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.domain import Job
from movie_review.media import ffmpeg as ff
from movie_review.media.frames import (
    FrameSamplingError,
    SamplingConfig,
    _select_expression,
    extract_frame,
    extract_scene_frames,
    frame_filename,
    frame_index_for,
    frames_cache_key,
    sample_movie,
    sample_timestamps,
)
from movie_review.pipeline.progress import WorkProgress
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _is_batch_call(args: list[str]) -> bool:
    """The select pass, as opposed to the per-frame seek or the dHash pass."""
    return any(arg.startswith("select=") for arg in args)


def _fake_batch_run(
    recorded: list[list[str]],
    content_by_index: dict[int, bytes] | None = None,
    max_index: int | None = None,
) -> Callable[..., str]:
    """A run_fn that emulates the select pass, the per-frame seek and dHash.

    The dHash emulation renders each listed frame to a 72-byte block derived
    from the file's bytes: identical frames hash identically, different
    frames hash far apart (a digest spread over the block).
    """

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
        if _is_batch_call(args):
            vf = args[args.index("-vf") + 1]
            indices = [int(match) for match in re.findall(r"eq\(n\\,(?P<i>\d+)\)", vf)]
            pattern = Path(args[-1])
            pattern.parent.mkdir(parents=True, exist_ok=True)
            for position, index in enumerate(indices, start=1):
                if max_index is not None and index > max_index:
                    continue  # past the last frame: the select filter drops it
                content = (content_by_index or {}).get(index, f"frame-{index}".encode())
                Path(str(pattern) % position).write_bytes(content)
            return ""
        # Per-frame seek: content names the requested timestamp.
        timestamp = args[args.index("-ss") + 1]
        out = Path(args[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(f"seek-{timestamp}".encode())
        return ""

    return _run


def _source(tmp_path: Path) -> Path:
    src = tmp_path / "proxy.mp4"
    src.write_bytes(b"proxy-bytes")
    return src


def test_frame_index_for_rounds_to_nearest() -> None:
    assert frame_index_for(0.0, 24.0) == 0
    assert frame_index_for(1.0, 24.0) == 24
    assert frame_index_for(0.5, 2.0) == 1
    assert frame_index_for(10.4, 25.0) == 260
    with pytest.raises(FrameSamplingError):
        frame_index_for(1.0, 0.0)
    with pytest.raises(FrameSamplingError):
        frame_index_for(1.0, -24.0)


def test_select_expression_escapes_the_filter_commas() -> None:
    assert _select_expression([5, 47]) == r"eq(n\,5)+eq(n\,47)"
    assert "," not in _select_expression([5]).replace(r"\,", "")


def test_batch_is_one_pass_and_maps_stream_order(tmp_path: Path) -> None:
    src = _source(tmp_path)
    recorded: list[list[str]] = []
    run_fn = _fake_batch_run(recorded, {0: b"A", 40: b"B", 80: b"C"})
    timestamps = sample_timestamps(0.0, 5.0, 3)  # [0.0, 1.666..., 3.333...]

    dest = tmp_path / "scene_000001"
    paths = extract_scene_frames(src, timestamps, dest, "scene_000001", 24.0, run_fn=run_fn)

    # One pass, not one per frame.
    assert len(recorded) == 1
    assert "-vf" in recorded[0]
    # The i-th output is the i-th requested timestamp, on the deterministic name.
    assert [p.name for p in paths] == [frame_filename("scene_000001", t) for t in timestamps]
    assert paths[0].read_bytes() == b"A"
    assert paths[1].read_bytes() == b"B"
    assert paths[2].read_bytes() == b"C"
    assert not (dest / ".batch").exists()


def test_single_frame_takes_the_per_frame_path(tmp_path: Path) -> None:
    src = _source(tmp_path)
    recorded: list[list[str]] = []
    run_fn = _fake_batch_run(recorded)

    dest = tmp_path / "scene_000001"
    paths = extract_scene_frames(src, [1.0], dest, "scene_000001", 24.0, run_fn=run_fn)

    assert len(recorded) == 1
    assert "-vf" not in recorded[0]
    assert "-ss" in recorded[0]
    assert paths[0].read_bytes() == b"seek-1.000"


def test_fallback_without_fps(tmp_path: Path) -> None:
    src = _source(tmp_path)
    recorded: list[list[str]] = []
    run_fn = _fake_batch_run(recorded)
    timestamps = sample_timestamps(0.0, 10.0, 4)

    paths = extract_scene_frames(src, timestamps, tmp_path / "s", "s", None, run_fn=run_fn)

    assert len(recorded) == len(timestamps)
    assert all("-vf" not in args for args in recorded)
    assert all(p.is_file() for p in paths)


def test_fallback_on_index_collision(tmp_path: Path) -> None:
    src = _source(tmp_path)
    recorded: list[list[str]] = []
    run_fn = _fake_batch_run(recorded)
    # 0.98 and 1.0 at 24 fps both round to frame 24 (23.52 and 24.0).
    timestamps = [0.98, 1.0]

    paths = extract_scene_frames(src, timestamps, tmp_path / "s", "s", 24.0, run_fn=run_fn)

    assert len(recorded) == 2
    assert all("-vf" not in args for args in recorded)
    assert [p.name for p in paths] == [frame_filename("s", t) for t in timestamps]


def test_fallback_on_non_ascending_timestamps(tmp_path: Path) -> None:
    src = _source(tmp_path)
    recorded: list[list[str]] = []
    run_fn = _fake_batch_run(recorded)

    paths = extract_scene_frames(src, [2.0, 1.0], tmp_path / "s", "s", 24.0, run_fn=run_fn)

    assert len(recorded) == 2
    assert all("-vf" not in args for args in recorded)
    assert [p.name for p in paths] == [frame_filename("s", 2.0), frame_filename("s", 1.0)]


def test_fallback_when_the_pass_fails(tmp_path: Path) -> None:
    src = _source(tmp_path)
    recorded: list[list[str]] = []

    def _run(binary: str, args: list[str]) -> str:
        recorded.append(list(args))
        if "-vf" in args:
            raise ff.ProcessError(binary, args, "decode blew up")
        out = Path(args[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"seek-recovered")
        return ""

    timestamps = sample_timestamps(0.0, 5.0, 3)
    paths = extract_scene_frames(src, timestamps, tmp_path / "s", "s", 24.0, run_fn=_run)

    # One failed pass, then three per-frame seeks.
    assert len(recorded) == 4
    assert paths[0].read_bytes() == b"seek-recovered"
    assert all(p.is_file() for p in paths)


def test_short_pass_finishes_the_tail_per_frame(tmp_path: Path) -> None:
    src = _source(tmp_path)
    recorded: list[list[str]] = []
    # The stream has frames 0..79 only: the 80th sample falls off the end.
    run_fn = _fake_batch_run(recorded, max_index=79)
    timestamps = sample_timestamps(0.0, 5.0, 3)  # indexes 0, 40, 80

    paths = extract_scene_frames(src, timestamps, tmp_path / "s", "s", 24.0, run_fn=run_fn)

    batch_calls = [args for args in recorded if "-vf" in args]
    seek_calls = [args for args in recorded if "-ss" in args]
    assert len(batch_calls) == 1
    assert len(seek_calls) == 1
    assert paths[0].read_bytes() == b"frame-0"
    assert paths[1].read_bytes() == b"frame-40"
    assert paths[2].read_bytes() == f"seek-{timestamps[2]:.3f}".encode()


def test_overlong_pass_is_an_error(tmp_path: Path) -> None:
    src = _source(tmp_path)
    recorded: list[list[str]] = []

    def _run(binary: str, args: list[str]) -> str:
        recorded.append(list(args))
        pattern = Path(args[-1])
        pattern.parent.mkdir(parents=True, exist_ok=True)
        for position in (1, 2, 3, 4):  # four files for two samples
            Path(str(pattern) % position).write_bytes(b"extra")
        return ""

    with pytest.raises(FrameSamplingError, match="produced 4 frames for 2 samples"):
        extract_scene_frames(src, [1.0, 2.0], tmp_path / "s", "s", 24.0, run_fn=_run)


def test_cache_key_binds_the_fps() -> None:
    cfg = SamplingConfig()
    scenes = [("s1", 0.0, 5.0)]
    assert frames_cache_key("h", scenes, cfg, 24.0) != frames_cache_key("h", scenes, cfg, 25.0)
    assert frames_cache_key("h", scenes, cfg, 24.0) != frames_cache_key("h", scenes, cfg)


def test_sample_movie_one_pass_per_scene(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    src = _source(tmp_path)
    recorded: list[list[str]] = []
    progress: list[WorkProgress] = []

    result = sample_movie(
        src,
        [("scene_000001", 0.0, 5.0), ("scene_000002", 5.0, 35.0)],
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        cache=CacheManager(tmp_path / "cache"),
        fps=24.0,
        run_fn=_fake_batch_run(recorded),
        on_progress=progress.append,
    )

    # Two scenes, two passes -- not nine seeks.
    batch_calls = [args for args in recorded if _is_batch_call(args)]
    assert len(batch_calls) == 2
    assert len(result.frames) == 3 + 6
    assert all(f.path.is_file() for f in result.frames)
    # The scene-2 frames carry scene-2 timestamps and names.
    scene_2 = [f for f in result.frames if f.scene_id == "scene_000002"]
    assert scene_2[0].timestamp == pytest.approx(5.0)
    assert scene_2[0].path.name.startswith("scene_000002-")
    # Progress is still per frame, in order.
    assert [p.done for p in progress] == list(range(1, 10))
    assert result.manifest_path.is_file()
    conn.close()


def test_sample_movie_without_fps_keeps_per_frame(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    src = _source(tmp_path)
    recorded: list[list[str]] = []

    result = sample_movie(
        src,
        [("scene_000001", 0.0, 5.0)],
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        cache=CacheManager(tmp_path / "cache"),
        run_fn=_fake_batch_run(recorded),
    )

    seek_calls = [args for args in recorded if "-ss" in args]
    assert len(seek_calls) == 3
    assert not any(_is_batch_call(args) for args in recorded)
    assert len(result.frames) == 3
    conn.close()


@pytest.mark.ffmpeg
def test_batch_output_matches_per_frame_seeks_on_a_real_clip(tmp_path: Path) -> None:
    src = tmp_path / "t.mp4"
    ff.check(
        "ffmpeg",
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=24:duration=2",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-an",
            str(src),
        ],
    )
    # Frame boundaries whose millisecond-quantised seek lands on the same
    # frame as round(t * fps): 5/24 -> 0.208, 12/24 -> 0.500, 24/24 -> 1.000,
    # 47/24 -> 1.958.
    indices = [5, 12, 24, 47]
    fps = 24.0
    timestamps = [index / fps for index in indices]

    recorded: list[list[str]] = []
    dest = tmp_path / "batch"
    batch_paths = extract_scene_frames(
        src, timestamps, dest, "scene_000001", fps, run_fn=_fake_real(recorded)
    )

    assert len([args for args in recorded if "-vf" in args]) == 1
    for index, timestamp, path in zip(indices, timestamps, batch_paths, strict=True):
        seek = tmp_path / f"seek_{index}.jpg"
        extract_frame(src, timestamp, seek, run_fn=ff.check)
        assert path.read_bytes() == seek.read_bytes(), f"frame {index} differs"


def _fake_real(recorded: list[list[str]]) -> Callable[..., str]:
    """Record the batch call, then run the real ffmpeg for it."""

    def _run(binary: str, args: list[str]) -> str:
        recorded.append(list(args))
        return ff.check(binary, args)

    return _run
