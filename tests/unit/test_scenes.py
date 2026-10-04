"""T013 acceptance: PySceneDetect adapter finds cuts and classifies failures."""

import shutil
from pathlib import Path

import pytest

from movie_review.config.settings import load_settings
from movie_review.media import ffmpeg as ff
from movie_review.media.scenes import SceneDetectionError, detect_scenes

NEEDS_FFMPEG = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe binaries not installed",
)


def _segment(path: Path, pattern: str) -> Path:
    ff.check(
        "ffmpeg",
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"{pattern}=size=320x240:rate=25:duration=1",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-an",
            str(path),
        ],
    )
    return path


def _continuous(path: Path) -> Path:
    return _segment(path, "testsrc")


def _with_cut(path: Path, tmp_path: Path) -> Path:
    first = _segment(tmp_path / "a.mp4", "testsrc")
    second = _segment(tmp_path / "b.mp4", "smptebars")
    listing = tmp_path / "parts.txt"
    listing.write_text(f"file '{first}'\nfile '{second}'\n", encoding="utf-8")
    ff.check(
        "ffmpeg", ["-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(path)]
    )
    return path


def test_unknown_detector_rejected(tmp_path: Path) -> None:
    with pytest.raises(SceneDetectionError, match="Unknown detector"):
        detect_scenes(tmp_path / "m.mp4", detector="nope")


def test_missing_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(SceneDetectionError, match="not found"):
        detect_scenes(tmp_path / "absent.mp4")


def test_bad_min_scene_len_rejected(tmp_path: Path) -> None:
    with pytest.raises(SceneDetectionError, match="min_scene_len"):
        detect_scenes(tmp_path / "m.mp4", min_scene_len=0)
    # Argument validation precedes I/O: an existing file fails the same way.
    existing = tmp_path / "e.mp4"
    existing.write_bytes(b"not-a-video")
    with pytest.raises(SceneDetectionError, match="min_scene_len"):
        detect_scenes(existing, min_scene_len=-5)


@NEEDS_FFMPEG
def test_continuous_video_is_one_scene(tmp_path: Path) -> None:
    result = detect_scenes(_continuous(tmp_path / "c.mp4"))
    assert len(result.cuts) == 1
    assert result.cuts[0].start == pytest.approx(0.0, abs=0.1)
    assert result.cuts[0].end == pytest.approx(1.0, abs=0.1)
    assert result.fps > 0


@NEEDS_FFMPEG
def test_hard_cut_found(tmp_path: Path) -> None:
    result = detect_scenes(_with_cut(tmp_path / "cut.mp4", tmp_path))
    assert len(result.cuts) == 2
    assert result.cuts[0].end == pytest.approx(1.0, abs=0.15)
    assert result.cuts[1].start == pytest.approx(1.0, abs=0.15)
    assert result.cuts[1].end == pytest.approx(2.0, abs=0.15)


@NEEDS_FFMPEG
def test_high_threshold_suppresses_cut(tmp_path: Path) -> None:
    result = detect_scenes(
        _with_cut(tmp_path / "cut.mp4", tmp_path), detector="content", threshold=100.0
    )
    assert len(result.cuts) == 1


def test_detection_settings_defaults() -> None:
    detection = load_settings().pipeline.scene_detection
    assert detection.detector == "adaptive"
    assert detection.threshold is None
    assert detection.min_scene_len == 15
