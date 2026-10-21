"""Drop a job's artifacts, so the stages that made them run again.

``--force`` means "redo this work". The stages are idempotent and their
results are content-addressed, so a cache hit is not a stale answer: it is
the same answer. Removing the artifacts is therefore enough — the stage
re-runs, and where the work is genuinely unchanged the cache answers and the
artifact is rewritten.

This never touches the movie analysis, the script or the render manifest of
a stage that was not selected.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

#: The artifact stages, and the stage name each one records. The stages that
#: write into a shared directory record their stage name, not the directory.
STAGE_ARTIFACTS: dict[str, str] = {
    "ingest": "ingest",
    "scenes": "scenes",
    "transcript": "transcript",
    "vision": "vision",
    "characters": "characters",
    "locations": "locations",
    "events": "events",
    "arcs": "arcs",
    "themes": "themes",
    "twists": "twists",
    "story": "story",
    "review": "review",
    "verify": "verify",
    "review-translate": "review-translate",
    "tts-chunks": "tts",
    "tts-concat": "tts",
    "tts-reconcile": "tts",
    "render-manifest": "render",
    "subtitles": "render",
    "render": "render",
    "quality": "quality",
}


def invalidate_artifacts(
    conn: sqlite3.Connection,
    job_id: str,
    stages: list[str],
    jobs_dir: str | Path,
) -> list[str]:
    """Remove the artifacts of the named stages; returns what was removed.

    The artifact rows are the record of what a job produced, so they go with
    the files. Anything the stage did not record -- a frame that was never
    registered, a temporary file -- is left alone.
    """
    wanted = {STAGE_ARTIFACTS.get(stage, stage) for stage in stages}
    root = Path(jobs_dir) / job_id
    removed: list[str] = []

    for artifact in repo.list_artifacts(conn, job_id):
        if artifact.stage not in wanted:
            continue
        if artifact.relative_path:
            path = root / artifact.relative_path
            try:
                if path.is_file():
                    path.unlink()
                    removed.append(artifact.relative_path)
            except OSError as exc:
                with ulog.logging_context(job_id=job_id, stage="force"):
                    ulog.log_event(
                        _logger,
                        event="force.unlink_failed",
                        status="error",
                        path=artifact.relative_path,
                        error=str(exc),
                    )
        repo.delete_artifact(conn, artifact.artifact_id)

    with ulog.logging_context(job_id=job_id, stage="force"):
        ulog.log_event(
            _logger,
            event="force.invalidated",
            status="ok",
            stages=sorted(wanted),
            files=len(removed),
        )
    return removed
