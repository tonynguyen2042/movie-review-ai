"""Job-level artifact integrity scan (T073).

Verifies every recorded artifact file for a job against its expected
SHA-256. Missing files and hash mismatches are reported — never silently
replaced with guesses. Used by ``validate`` and resume paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from movie_review.artifacts.manager import (
    ArtifactIntegrityError,
    sha256_file,
)


@dataclass(frozen=True)
class ArtifactRecord:
    """One file whose integrity must hold."""

    stage: str
    filename: str
    expected_hash: str


@dataclass(frozen=True)
class IntegrityReport:
    """Result of scanning a job's artifacts."""

    job_id: str
    checked: int = 0
    ok: int = 0
    missing: list[str] = field(default_factory=list)
    corrupt: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.missing and not self.corrupt


def scan_job_integrity(
    jobs_dir: str | Path, job_id: str, records: list[ArtifactRecord]
) -> IntegrityReport:
    """Hash-verify each record under ``<jobs_dir>/<job_id>``."""
    root = Path(jobs_dir) / job_id
    missing: list[str] = []
    corrupt: list[str] = []
    ok = 0
    for record in records:
        path = root / record.stage / record.filename
        if not path.is_file():
            missing.append(f"{record.stage}/{record.filename}")
            continue
        try:
            actual = sha256_file(path)
        except OSError:
            missing.append(f"{record.stage}/{record.filename}")
            continue
        if actual != record.expected_hash:
            corrupt.append(f"{record.stage}/{record.filename}")
        else:
            ok += 1
    return IntegrityReport(
        job_id=job_id, checked=len(records), ok=ok, missing=missing, corrupt=corrupt
    )


def verify_or_raise(
    jobs_dir: str | Path, job_id: str, records: list[ArtifactRecord]
) -> IntegrityReport:
    """Like :func:`scan_job_integrity` but raises on the first problem."""
    report = scan_job_integrity(jobs_dir, job_id, records)
    if report.missing:
        raise FileNotFoundError(f"Missing artifacts for {job_id}: {report.missing}")
    if report.corrupt:
        first = report.corrupt[0]
        raise ArtifactIntegrityError(Path(first), "recorded", "mismatched")
    return report
