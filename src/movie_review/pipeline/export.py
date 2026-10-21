"""Copy a finished job's output set into the directory the operator asked for.

The `--output` flag used to reach nothing but a log line, and
`settings.paths.output_dir` was never read by any code, so a run left its
results buried under the job directory.

This is the first part of the output set described in README section 98. The
script in Markdown and the final manifest join it in T151; the files that
exist are copied now, and a file that a job did not produce is skipped rather
than reported as a failure.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

#: Artifact path inside the job directory -> name in the output directory.
#: A job that did not produce one of these is not a failed export; the file
#: simply is not there to copy.
OUTPUT_FILES: dict[str, str] = {
    "render/review.mp4": "review.mp4",
    "tts/narration.wav": "narration.wav",
    "render/review.srt": "review.srt",
    "movie-analysis.json": "movie-analysis.json",
    "qc/quality-report.json": "quality-report.json",
}


def export_output(jobs_dir: str | Path, job_id: str, output_dir: str | Path) -> list[Path]:
    """Copy the job's output files into ``output_dir``.

    Returns the files that were written. A job directory that does not hold
    the file contributes nothing, so an export of a job that stopped early
    copies what exists rather than failing.
    """
    job_dir = Path(jobs_dir) / job_id
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for source, name in OUTPUT_FILES.items():
        origin = job_dir / source
        if not origin.is_file():
            continue
        destination = target / name
        shutil.copy2(origin, destination)
        written.append(destination)

    with ulog.logging_context(job_id=job_id, stage="export"):
        ulog.log_event(
            _logger,
            event="export.completed",
            status="ok",
            output_dir=str(target),
            files=len(written),
        )
    return written
