"""Remove the intermediates a job has finished with.

README section 83: the system keeps the important artifacts and deletes the
temporary frames after a successful analysis. Section 84 puts the frames in
the "optional cleanup" list. A feature-length run leaves hundreds of
megabytes of JPEG frames behind, and they are regenerable.

The manifest is kept: it is the record of what was sampled, it is tiny, and
the artifact table points at it.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

#: The directory the frame images live in, under the job's frames stage.
FRAMES_DIRNAME = "frames"


def cleanup_intermediates(job_dir: str | Path, *, keep: bool = False) -> list[Path]:
    """Delete the regenerable intermediates of a job.

    ``keep`` leaves everything alone — that is what ``--keep-intermediates``
    asks for. A job that has no frames yet contributes nothing, and one that
    has already been cleaned contributes nothing either.
    """
    root = Path(job_dir)
    if keep:
        return []

    removed: list[Path] = []
    frames = root / FRAMES_DIRNAME
    if frames.is_dir():
        # The manifest is the record of what was sampled; the images are the
        # bulk and are regenerable.
        for path in sorted(frames.rglob("*.jpg")):
            try:
                path.unlink()
                removed.append(path)
            except OSError as exc:
                _logger.warning("Could not remove %s: %s", path, exc)
        # The now-empty scene directories.
        for path in sorted(frames.glob("scene_*")):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

    if removed:
        with ulog.logging_context(stage="cleanup"):
            ulog.log_event(
                _logger,
                event="cleanup.completed",
                status="ok",
                frames=len(removed),
            )
    return removed
