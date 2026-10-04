"""PySceneDetect adapter: cut detection over a video file (T013).

Returns timestamped cuts; ID assignment, persistence, and lifecycle belong to
the T014 stage. Detection thresholds stay configurable (no hard-coding).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from scenedetect import (
    AdaptiveDetector,
    ContentDetector,
    SceneManager,
    VideoOpenFailure,
    open_video,
)

from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

DEFAULT_CONTENT_THRESHOLD = 27.0
DEFAULT_ADAPTIVE_THRESHOLD = 3.0
DEFAULT_MIN_SCENE_LEN = 15  # frames, per PySceneDetect convention

DETECTORS = ("adaptive", "content")


class SceneDetectionError(Exception):
    """Scene detection failed in a classified way."""


@dataclass(frozen=True)
class SceneCut:
    """One detected scene span in seconds."""

    start: float
    end: float


@dataclass(frozen=True)
class DetectionResult:
    """Detected cuts plus the source frame rate.

    Cuts always cover ``[0, duration]``: a video with no cuts yields one cut
    spanning the whole file.
    """

    cuts: list[SceneCut]
    fps: float


def detect_scenes(
    path: str | Path,
    *,
    detector: str = "adaptive",
    threshold: float | None = None,
    min_scene_len: int = DEFAULT_MIN_SCENE_LEN,
) -> DetectionResult:
    """Detect scene cuts in ``path``; raises :class:`SceneDetectionError` on failure."""
    kind = detector.lower()
    if kind not in DETECTORS:
        raise SceneDetectionError(f"Unknown detector {detector!r}; expected one of {DETECTORS}")
    src = Path(path)
    if not src.is_file():
        raise SceneDetectionError(f"Input file not found: {src}")
    if min_scene_len <= 0:
        raise SceneDetectionError(f"min_scene_len must be positive frames: {min_scene_len}")
    if kind == "content":
        algo: ContentDetector | AdaptiveDetector = ContentDetector(
            threshold=DEFAULT_CONTENT_THRESHOLD if threshold is None else threshold,
            min_scene_len=min_scene_len,
        )
    elif kind == "adaptive":
        algo = AdaptiveDetector(
            adaptive_threshold=DEFAULT_ADAPTIVE_THRESHOLD if threshold is None else threshold,
            min_scene_len=min_scene_len,
        )

    try:
        video = open_video(str(src))
    except VideoOpenFailure as exc:
        raise SceneDetectionError(f"Cannot open {src}: {exc}") from exc
    manager = SceneManager()
    manager.add_detector(algo)
    try:
        manager.detect_scenes(video)
    except Exception as exc:  # PySceneDetect error hierarchy shifts across versions; classify here.
        raise SceneDetectionError(f"Detection failed for {src}: {exc}") from exc
    cuts = [
        SceneCut(start=start.seconds, end=end.seconds) for start, end in manager.get_scene_list()
    ]
    if not cuts:
        duration = video.duration.seconds
        if duration <= 0:
            raise SceneDetectionError(f"Cannot determine duration for {src}")
        cuts = [SceneCut(start=0.0, end=duration)]
    fps = float(video.frame_rate)
    if fps <= 0:
        raise SceneDetectionError(f"Cannot determine fps for {src}")
    with ulog.logging_context(stage="scene-detection"):
        ulog.log_event(_logger, event="detection.completed", status="ok", cuts=len(cuts))
    return DetectionResult(cuts=cuts, fps=fps)
