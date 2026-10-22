"""T012 acceptance: proxy generation, reuse, and failure handling."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, MovieMetadata
from movie_review.media import ffmpeg as ff
from movie_review.media.proxy import ProxyError, ProxyResult, _scale_filter, generate_proxy
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


@dataclass
class Harness:
    conn: sqlite3.Connection
    jobs_dir: Path
    cache: CacheManager
    source: Path

    def proxy(self, **overrides: object) -> ProxyResult:
        kwargs: dict[str, object] = {
            "job_id": "job_1",
            "jobs_dir": self.jobs_dir,
            "conn": self.conn,
            "cache": self.cache,
            "run_fn": _fake_run__proxy,
            "probe_fn": _fake_probe__proxy,
        }
        kwargs.update(overrides)
        return generate_proxy(self.source, **kwargs)  # type: ignore[arg-type]


def _harness__proxy(tmp_path: Path) -> Harness:
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


def _fake_run__proxy(binary: str, args: list[str]) -> str:
    dest = Path(args[-1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"proxy-bytes")
    return ""


def _fake_probe__proxy(path: str) -> MovieMetadata:
    return MovieMetadata(
        file=path,
        sha256="b" * 64,
        duration_seconds=1.0,
        width=1280,
        height=720,
        fps=25.0,
        video_codec="h264",
    )


def test_proxy_happy_path(tmp_path: Path) -> None:
    result = _harness__proxy(tmp_path).proxy()
    assert result.cache_hit is False
    assert (result.width, result.height) == (1280, 720)
    assert result.path.is_file()


def test_proxy_artifact_recorded(tmp_path: Path) -> None:
    harness = _harness__proxy(tmp_path)
    harness.proxy()
    artifact = repo.get_artifact(harness.conn, "job_1-proxy-video")
    assert artifact is not None
    assert artifact.stage == "proxy"


def test_proxy_second_run_hits_cache(tmp_path: Path) -> None:
    harness = _harness__proxy(tmp_path)
    harness.proxy()

    def _boom(binary: str, args: list[str]) -> str:
        raise AssertionError("ffmpeg must not run on cache hit")

    result = harness.proxy(run_fn=_boom)
    assert result.cache_hit is True


def test_proxy_tampered_dest_regenerates(tmp_path: Path) -> None:
    harness = _harness__proxy(tmp_path)
    first = harness.proxy()
    first.path.write_bytes(b"tampered")
    calls: list[int] = []

    def _counting(binary: str, args: list[str]) -> str:
        calls.append(1)
        return _fake_run__proxy(binary, args)

    harness.proxy(run_fn=_counting)
    assert calls == [1]


def test_proxy_missing_source(tmp_path: Path) -> None:
    harness = _harness__proxy(tmp_path)
    harness.source.unlink()
    with pytest.raises(ProxyError, match="not found"):
        harness.proxy()


def test_proxy_bad_config(tmp_path: Path) -> None:
    harness = _harness__proxy(tmp_path)
    with pytest.raises(ProxyError, match="dimensions"):
        harness.proxy(max_width=0)
    with pytest.raises(ProxyError, match="CRF"):
        harness.proxy(crf=99)


def test_proxy_run_failure(tmp_path: Path) -> None:
    harness = _harness__proxy(tmp_path)

    def _fail(binary: str, args: list[str]) -> str:
        raise ff.ProcessError(binary, args, "boom")

    with pytest.raises(ProxyError, match="Cannot generate proxy"):
        harness.proxy(run_fn=_fail)


def test_proxy_settings_defaults() -> None:
    proxy = load_settings().media.proxy
    assert (proxy.max_width, proxy.max_height) == (1280, 720)
    assert proxy.crf == 23


def test_the_scale_filter_keeps_both_sides_even() -> None:
    """libx264 with yuv420p refuses an odd side; 1920x1080 in an 854x480 box
    otherwise lands on 853x480 and kills the run at the proxy."""
    assert "force_divisible_by=2" in _scale_filter(854, 480)
    assert "force_original_aspect_ratio=decrease" in _scale_filter(1280, 720)


@pytest.mark.ffmpeg
def test_proxy_with_an_odd_box_stays_encodable(tmp_path: Path) -> None:
    """A box whose aspect ratio does not divide evenly must still encode.

    854x480 is the reported failure: ffmpeg fits 1920x1080 into it and computes
    an odd width, libx264 refuses it, and the stage dies with "width not
    divisible by 2" before any scene is sampled.
    """
    harness = _harness__proxy(tmp_path)
    source = tmp_path / "big.mp4"
    ff.check(
        "ffmpeg",
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1920x1080:rate=25:duration=1",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-an",
            str(source),
        ],
    )
    harness.source = source
    result = harness.proxy(run_fn=ff.check, probe_fn=ff.probe, max_width=854, max_height=480)
    # 1920x1080 into an 854x480 box wants 853.3 px of width; rounding to the
    # nearest even value gives 852 or 854 depending on ffmpeg's align step.
    # What matters is that the encoder accepted it and nothing exceeds the box.
    assert result.width % 2 == 0 and result.height % 2 == 0
    assert result.width in (852, 854)
    assert result.height == 480
    assert result.width <= 854 and result.height <= 480


@pytest.mark.ffmpeg
def test_proxy_real_end_to_end(tmp_path: Path) -> None:
    harness = _harness__proxy(tmp_path)
    source = tmp_path / "big.mp4"
    ff.check(
        "ffmpeg",
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1920x1080:rate=25:duration=1",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-an",
            str(source),
        ],
    )
    harness.source = source
    result = harness.proxy(run_fn=ff.check)
    assert (result.width, result.height) == (1280, 720)
    assert result.cache_hit is False
    again = harness.proxy(run_fn=ff.check)
    assert again.cache_hit is True
