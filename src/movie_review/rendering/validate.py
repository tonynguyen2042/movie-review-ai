"""Render output validation (T062, spec section 94).

Verifies files exist, streams/durations match the manifest, segments tile
without gaps, and subtitles parse within the video duration. Returns a
report; quality gating (T068) decides job fate from it.
"""

from __future__ import annotations

import logging
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from movie_review.domain import MovieMetadata, RenderManifest
from movie_review.media import ffmpeg as ff
from movie_review.rendering.subtitles import parse_srt
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)


class RenderValidationError(Exception):
    """Validation could not run (missing inputs, unreadable files)."""


@dataclass(frozen=True)
class ValidationCheck:
    """One named check with its outcome."""

    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class ValidationReport:
    """Full validation outcome; ``ok`` requires every check to pass."""

    checks: list[ValidationCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True only when every check passed."""
        return bool(self.checks) and all(check.passed for check in self.checks)

    def failures(self) -> list[ValidationCheck]:
        """Failing checks only."""
        return [check for check in self.checks if not check.passed]


def _probe_video(
    path: Path, probe_fn: Any, manifest_total: float
) -> tuple[list[ValidationCheck], MovieMetadata | None]:
    try:
        meta = probe_fn(str(path))
        duration = float(getattr(meta, "duration_seconds", 0.0))
    except (ff.ProbeError, ff.ProcessError, AttributeError, TypeError, ValueError) as exc:
        return [ValidationCheck("video.probe", False, f"unreadable: {exc}")], None
    checks = [ValidationCheck("video.probe", True)]
    tolerance = max(2.0, manifest_total * 0.05)
    if abs(duration - manifest_total) <= tolerance:
        checks.append(ValidationCheck("video.duration", True, f"{duration:.1f}s"))
    else:
        checks.append(
            ValidationCheck(
                "video.duration",
                False,
                f"{duration:.1f}s vs manifest {manifest_total:.1f}s",
            )
        )
    return checks, meta


def _check_audio(path: Path | None, manifest_total: float) -> list[ValidationCheck]:
    if path is None:
        return [ValidationCheck("audio.present", False, "no narration supplied")]
    if not path.is_file():
        return [ValidationCheck("audio.present", False, f"missing: {path}")]
    try:
        with wave.open(str(path), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
    except (wave.Error, OSError, ZeroDivisionError) as exc:
        return [ValidationCheck("audio.readable", False, f"unreadable: {exc}")]
    checks = [
        ValidationCheck("audio.present", True),
        ValidationCheck("audio.readable", True, f"{duration:.1f}s"),
    ]
    tolerance = max(2.0, manifest_total * 0.05)
    if abs(duration - manifest_total) <= tolerance:
        checks.append(ValidationCheck("audio.duration", True))
    else:
        checks.append(
            ValidationCheck("audio.duration", False, f"{duration:.1f}s vs {manifest_total:.1f}s")
        )
    return checks


def _check_subtitles(path: Path | None, video_duration: float | None) -> list[ValidationCheck]:
    if path is None:
        return [ValidationCheck("subtitles.present", True, "not requested")]
    if not path.is_file():
        return [ValidationCheck("subtitles.present", False, f"missing: {path}")]
    try:
        cues = parse_srt(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [
            ValidationCheck("subtitles.present", True),
            ValidationCheck("subtitles.parseable", False, str(exc)),
        ]
    checks = [
        ValidationCheck("subtitles.present", True),
        ValidationCheck("subtitles.parseable", True, f"{len(cues)} cues"),
    ]
    if video_duration is not None and cues and cues[-1].end > video_duration + 2.0:
        checks.append(ValidationCheck("subtitles.within_video", False, "cues overrun video"))
    else:
        checks.append(ValidationCheck("subtitles.within_video", True))
    return checks


def _check_timeline(manifest: RenderManifest) -> list[ValidationCheck]:
    if not manifest.segments:
        return [ValidationCheck("timeline.nonempty", False, "no segments")]
    checks = [ValidationCheck("timeline.nonempty", True)]
    cursor = 0.0
    contiguous = True
    for segment in manifest.segments:
        if abs(segment.start - cursor) > 0.05:
            contiguous = False
            break
        cursor = segment.start + segment.duration
    checks.append(
        ValidationCheck(
            "timeline.contiguous",
            contiguous,
            "" if contiguous else f"gap near {cursor:.1f}s",
        )
    )
    return checks


def validate_render(
    video_path: str | Path,
    manifest: RenderManifest,
    narration_wav: str | Path | None = None,
    subtitles_srt: str | Path | None = None,
    probe_fn: Any = ff.probe,
) -> ValidationReport:
    """Validate render outputs against the manifest (no lifecycle changes)."""
    video = Path(video_path)
    checks: list[ValidationCheck] = []
    if not video.is_file():
        return ValidationReport([ValidationCheck("video.present", False, f"missing: {video}")])
    checks.append(ValidationCheck("video.present", True))
    video_checks, meta = _probe_video(video, probe_fn, manifest.total_seconds)
    checks.extend(video_checks)
    audio_path = Path(narration_wav) if narration_wav else None
    checks.extend(_check_audio(audio_path, manifest.total_seconds))
    duration = float(getattr(meta, "duration_seconds", 0.0)) if meta else None
    checks.extend(_check_subtitles(Path(subtitles_srt) if subtitles_srt else None, duration))
    checks.extend(_check_timeline(manifest))
    with ulog.logging_context(stage="render-validate"):
        ulog.log_event(
            _logger,
            event="validation.completed",
            status="ok" if all(c.passed for c in checks) else "failed",
        )
    return ValidationReport(checks=checks)
