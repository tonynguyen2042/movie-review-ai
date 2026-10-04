"""FFmpeg/ffprobe adapter primitives (T010).

Deterministic media tooling: stream probing into :class:`MovieMetadata` and
guarded subprocess execution. No model inference happens here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from fractions import Fraction

from movie_review.artifacts.manager import sha256_file
from movie_review.domain import MovieMetadata


class FFmpegError(Exception):
    """Base class for media tooling failures."""


class BinaryNotFoundError(FFmpegError):
    """The ffmpeg/ffprobe binary is not installed or not on PATH."""

    def __init__(self, binary: str) -> None:
        super().__init__(f"Required binary not found: {binary}")
        self.binary = binary


class ProbeError(FFmpegError):
    """ffprobe failed or its output could not be interpreted."""

    def __init__(self, path: str, detail: str) -> None:
        super().__init__(f"Cannot probe {path}: {detail}")
        self.path = path


class ProcessError(FFmpegError):
    """An ffmpeg run failed, timed out, or was interrupted."""

    def __init__(self, binary: str, args: list[str], detail: str) -> None:
        super().__init__(f"{binary} failed: {detail}")
        self.binary = binary
        self.argv = args


def _resolve(binary: str) -> str:
    """Return a runnable binary path or raise :class:`BinaryNotFoundError`."""
    found = shutil.which(binary)
    if found is None:
        raise BinaryNotFoundError(binary)
    return found


def ffmpeg_version(ffmpeg: str = "ffmpeg") -> str:
    """First line of ``ffmpeg -version`` (proves the binary runs)."""
    completed = run(ffmpeg, ["-version"])
    return completed.stdout.splitlines()[0]


def run(
    binary: str, args: list[str], timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a media binary, capturing output; failures raise :class:`ProcessError`."""
    executable = _resolve(binary)
    try:
        return subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProcessError(binary, args, f"timed out after {timeout}s") from exc
    except OSError as exc:
        raise ProcessError(binary, args, str(exc)) from exc


def check(binary: str, args: list[str], timeout: float | None = None) -> str:
    """Run and require exit 0; returns stdout, else raises :class:`ProcessError`."""
    completed = run(binary, args, timeout)
    if completed.returncode != 0:
        raise ProcessError(binary, args, (completed.stderr or "").strip()[-2000:])
    return completed.stdout


def _parse_rate(value: str | None) -> float | None:
    if not value:
        return None
    try:
        rate = float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def probe(path: str, ffprobe: str = "ffprobe") -> MovieMetadata:
    """Probe a media file into validated :class:`MovieMetadata` (FR-001)."""
    output = check(
        ffprobe,
        ["-v", "error", "-show_format", "-show_streams", "-of", "json", path],
    )
    try:
        info = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ProbeError(path, f"invalid JSON: {exc}") from exc
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProbeError(path, "no video stream")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = info.get("format", {})

    duration = _parse_float(fmt.get("duration")) or _parse_float(video.get("duration"))
    if duration is None or duration <= 0:
        raise ProbeError(path, "cannot determine duration")
    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
    if fps is None:
        raise ProbeError(path, "cannot determine fps")
    try:
        width = int(video["width"])
        height = int(video["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProbeError(path, f"cannot determine resolution: {exc}") from exc
    if width <= 0 or height <= 0:
        raise ProbeError(path, "invalid resolution")

    return MovieMetadata(
        file=path,
        sha256=sha256_file(path),
        duration_seconds=duration,
        width=width,
        height=height,
        fps=fps,
        video_codec=str(video.get("codec_name", "unknown")),
        audio_codec=str(audio["codec_name"]) if audio else None,
        container=str(fmt.get("format_name", "unknown")).split(",")[0],
    )


def _parse_float(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None
