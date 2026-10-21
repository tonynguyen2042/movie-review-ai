"""T010 acceptance: FFmpeg adapter probes media and classifies failures."""

import sys
from pathlib import Path

import pytest

from movie_review.config.settings import load_settings
from movie_review.media import ffmpeg as ff


def test_missing_binary_rejected() -> None:
    with pytest.raises(ff.BinaryNotFoundError):
        ff.run("definitely-not-a-binary-xyz", ["-version"])
    with pytest.raises(ff.BinaryNotFoundError):
        ff.ffmpeg_version("definitely-not-a-binary-xyz")


def test_timeout_wrapped() -> None:
    with pytest.raises(ff.ProcessError, match="timed out"):
        ff.run(sys.executable, ["-c", "import time; time.sleep(30)"], timeout=0.5)


def test_nonzero_exit_wrapped() -> None:
    with pytest.raises(ff.ProcessError):
        ff.check(sys.executable, ["-c", "raise SystemExit(3)"])
    completed = ff.run(sys.executable, ["-c", "raise SystemExit(3)"])
    assert completed.returncode == 3


def _make_fixture(path: Path, audio: bool = True) -> Path:
    inputs = ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=1"]
    if audio:
        inputs += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
        audio_args = ["-c:a", "aac"]
    else:
        audio_args = ["-an"]
    ff.check(
        "ffmpeg",
        ["-y", *inputs, "-pix_fmt", "yuv420p", "-c:v", "libx264", *audio_args, str(path)],
    )
    return path


@pytest.mark.ffmpeg
def test_probe_fixture(tmp_path: Path) -> None:
    meta = ff.probe(str(_make_fixture(tmp_path / "t.mp4")))
    assert (meta.width, meta.height) == (320, 240)
    assert meta.duration_seconds == pytest.approx(1.0, abs=0.1)
    assert meta.fps == pytest.approx(25.0)
    assert meta.video_codec == "h264"
    assert meta.audio_codec == "aac"
    assert meta.container in ("mov", "mp4")
    assert len(meta.sha256) == 64
    assert meta.file.endswith("t.mp4")


@pytest.mark.ffmpeg
def test_probe_audio_only_rejected(tmp_path: Path) -> None:
    target = tmp_path / "a.wav"
    ff.check(
        "ffmpeg",
        ["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(target)],
    )
    with pytest.raises(ff.ProbeError, match="no video stream"):
        ff.probe(str(target))


@pytest.mark.ffmpeg
def test_probe_missing_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(ff.ProcessError):
        ff.probe(str(tmp_path / "absent.mp4"))


@pytest.mark.ffmpeg
def test_ffmpeg_version_runs() -> None:
    assert ff.ffmpeg_version().startswith("ffmpeg version")


def test_media_settings_defaults() -> None:
    media = load_settings().media
    assert media.ffmpeg == "ffmpeg"
    assert media.ffprobe == "ffprobe"
