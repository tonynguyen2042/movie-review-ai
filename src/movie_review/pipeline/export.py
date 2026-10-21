"""Export a finished job's output set, and render the script as Markdown.

T151. README section 1 and section 98 promise an output directory holding
``review.mp4``, ``review.srt``, ``narration.wav``, ``review-script.md``,
``movie-analysis.json``, ``quality-report.json``, ``manifest.json`` and
``thumbnail.png``.

Four of the eight were produced. The script in Markdown was never
rendered, the final manifest was never written, and ``--output`` reached
nothing but a log line -- so the promised directory did not exist.

The Markdown is derived from the structured script, never maintained
separately: the constitution's P3 says the structured data is the contract
and Markdown is presentation.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from movie_review.domain import ReviewScript
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
    "qc/thumbnail.png": "thumbnail.png",
}

#: The file the final manifest is written to.
MANIFEST_FILENAME = "manifest.json"
#: The Markdown rendering of the script.
SCRIPT_FILENAME = "review-script.md"


class ExportError(Exception):
    """The export failed in a classified way."""


@dataclass
class ExportResult:
    """The files the export wrote."""

    files: list[Path]
    manifest_path: Path
    script_path: Path


def render_script_markdown(script: ReviewScript) -> str:
    """The script as Markdown.

    The Markdown is derived from the structured script, which is the
    contract; this is only its presentation.
    """
    lines: list[str] = []
    for section in script.sections:
        lines.append(f"## {section.type.replace('_', ' ').title()}")
        lines.append("")
        for paragraph in section.paragraphs:
            lines.append(paragraph.text)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_manifest(
    job_id: str,
    input_file: str,
    input_sha256: str,
    models: dict[str, str],
    metrics: dict[str, Any],
    status: str,
    outputs: dict[str, str],
) -> dict[str, Any]:
    """The final manifest of README section 95."""
    return {
        "job_id": job_id,
        "input": {
            "file": input_file,
            "sha256": input_sha256,
        },
        "output": outputs,
        "models": models,
        "metrics": metrics,
        "status": status,
    }


def export_output(
    jobs_dir: str | Path,
    job_id: str,
    output_dir: str | Path,
    *,
    script: ReviewScript | None = None,
    manifest: dict[str, Any] | None = None,
) -> ExportResult:
    """Copy the job's output files into ``output_dir``.

    Returns the files that were written. A job directory that does not hold
    the file contributes nothing, so an export of a job that stopped early
    copies what exists rather than failing.
    """
    job_dir = Path(jobs_dir) / job_id
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    outputs: dict[str, str] = {}
    for source, name in OUTPUT_FILES.items():
        origin = job_dir / source
        if not origin.is_file():
            continue
        destination = target / name
        shutil.copy2(origin, destination)
        written.append(destination)
        outputs[name] = destination.name

    script_path = target / SCRIPT_FILENAME
    if script is not None:
        script_path.write_text(render_script_markdown(script), encoding="utf-8")
        written.append(script_path)
        outputs[SCRIPT_FILENAME] = SCRIPT_FILENAME

    manifest_path = target / MANIFEST_FILENAME
    if manifest is not None:
        import json

        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        written.append(manifest_path)
        outputs[MANIFEST_FILENAME] = MANIFEST_FILENAME

    with ulog.logging_context(job_id=job_id, stage="export"):
        ulog.log_event(
            _logger,
            event="export.completed",
            status="ok",
            output_dir=str(target),
            files=len(written),
        )
    return ExportResult(files=written, manifest_path=manifest_path, script_path=script_path)
