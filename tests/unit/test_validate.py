"""T062 acceptance: render validation against manifest and files."""

import shutil
import wave
from pathlib import Path

import pytest

from movie_review.domain import ManifestSegment, MovieMetadata, RenderManifest
from movie_review.media import ffmpeg as ff
from movie_review.rendering.subtitles import build_cues, format_srt
from movie_review.rendering.validate import ValidationReport, validate_render

NEEDS_FFMPEG = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe binaries not installed",
)


def _manifest() -> RenderManifest:
    return RenderManifest(
        segments=[
            ManifestSegment(
                paragraph_id="p1",
                start=0.0,
                duration=2.0,
                scene_id="s1",
                clip_start=0.0,
                clip_end=2.0,
            ),
            ManifestSegment(
                paragraph_id="p2",
                start=2.0,
                duration=3.0,
                scene_id="s2",
                clip_start=1.0,
                clip_end=4.0,
            ),
        ],
        total_seconds=5.0,
        source_seconds=5.0,
    )


def _meta(duration: float) -> MovieMetadata:
    return MovieMetadata(
        file="v.mp4",
        sha256="a" * 64,
        duration_seconds=duration,
        width=1920,
        height=1080,
        fps=30.0,
        video_codec="h264",
    )


def _wav(path: Path, seconds: float, rate: int = 16000) -> Path:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00" * int(seconds * rate) * 2)
    return path


def _srt(path: Path) -> Path:
    cues = build_cues(_manifest(), {"p1": "Hello world.", "p2": "More words here."})
    path.write_text(format_srt(cues), encoding="utf-8")
    return path


def test_happy_path(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake-video")
    report = validate_render(
        video,
        _manifest(),
        _wav(tmp_path / "n.wav", 5.0),
        _srt(tmp_path / "r.srt"),
        probe_fn=lambda p: _meta(5.0),
    )
    assert isinstance(report, ValidationReport)
    assert report.ok is True
    assert report.failures() == []


def test_missing_video(tmp_path: Path) -> None:
    report = validate_render(tmp_path / "absent.mp4", _manifest(), probe_fn=lambda p: _meta(5.0))
    assert report.ok is False
    assert report.failures()[0].name == "video.present"


def test_duration_mismatch(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    report = validate_render(video, _manifest(), probe_fn=lambda p: _meta(60.0))
    assert report.ok is False
    assert "video.duration" in {f.name for f in report.failures()}


def test_unreadable_audio(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    bad = tmp_path / "n.wav"
    bad.write_bytes(b"not-a-wav")
    report = validate_render(video, _manifest(), bad, probe_fn=lambda p: _meta(5.0))
    assert report.ok is False
    assert any(f.name == "audio.readable" for f in report.failures())


def test_malformed_subtitles(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    bad = tmp_path / "r.srt"
    bad.write_text("garbage", encoding="utf-8")
    report = validate_render(
        video, _manifest(), _wav(tmp_path / "n.wav", 5.0), bad, probe_fn=lambda p: _meta(5.0)
    )
    assert report.ok is False
    assert any(f.name == "subtitles.parseable" for f in report.failures())


def test_gapped_timeline(tmp_path: Path) -> None:
    manifest = RenderManifest(
        segments=[
            ManifestSegment(
                paragraph_id="p1",
                start=0.0,
                duration=2.0,
                scene_id="s1",
                clip_start=0.0,
                clip_end=2.0,
            ),
            ManifestSegment(
                paragraph_id="p2",
                start=5.0,
                duration=3.0,
                scene_id="s2",
                clip_start=0.0,
                clip_end=3.0,
            ),
        ],
        total_seconds=8.0,
        source_seconds=5.0,
    )
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    report = validate_render(video, manifest, probe_fn=lambda p: _meta(8.0))
    assert report.ok is False
    assert any(f.name == "timeline.contiguous" for f in report.failures())


@NEEDS_FFMPEG
def test_real_end_to_end(tmp_path: Path) -> None:
    source = tmp_path / "src.mp4"
    ff.check(
        "ffmpeg",
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=25:duration=2",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-an",
            str(source),
        ],
    )
    narration = tmp_path / "n.wav"
    ff.check(
        "ffmpeg",
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:a",
            "pcm_s16le",
            str(narration),
        ],
    )
    manifest = RenderManifest(
        segments=[
            ManifestSegment(
                paragraph_id="p1",
                start=0.0,
                duration=2.0,
                scene_id="s1",
                clip_start=0.0,
                clip_end=2.0,
            ),
        ],
        total_seconds=2.0,
        source_seconds=2.0,
    )
    from movie_review.rendering.subtitles import format_srt as _fmt

    srt = tmp_path / "r.srt"
    srt.write_text(_fmt(build_cues(manifest, {"p1": "Hello world."})), encoding="utf-8")
    report = validate_render(source, manifest, narration, srt)
    assert report.ok is True
