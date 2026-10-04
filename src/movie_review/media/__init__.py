"""Media probing, process, and scene-detection adapters (T010, T013)."""

from movie_review.media.ffmpeg import (
    BinaryNotFoundError,
    FFmpegError,
    ProbeError,
    ProcessError,
    check,
    ffmpeg_version,
    probe,
    run,
)
from movie_review.media.scenes import (
    DEFAULT_ADAPTIVE_THRESHOLD,
    DEFAULT_CONTENT_THRESHOLD,
    DEFAULT_MIN_SCENE_LEN,
    DETECTORS,
    DetectionResult,
    SceneCut,
    SceneDetectionError,
    detect_scenes,
)

__all__ = [
    "DEFAULT_ADAPTIVE_THRESHOLD",
    "DEFAULT_CONTENT_THRESHOLD",
    "DEFAULT_MIN_SCENE_LEN",
    "DETECTORS",
    "BinaryNotFoundError",
    "DetectionResult",
    "FFmpegError",
    "ProbeError",
    "ProcessError",
    "SceneCut",
    "SceneDetectionError",
    "check",
    "detect_scenes",
    "ffmpeg_version",
    "probe",
    "run",
]
