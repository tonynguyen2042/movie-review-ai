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
    UnsafePathError,
    resolve_relative,
    sha256_file,
)


@dataclass(frozen=True)
class ArtifactRecord:
    """One file whose integrity must hold.

    ``relative_path`` is the path under the job root, exactly as the stage wrote
    it -- ``scenes/scenes.json``, ``media/media.json``, ``movie-analysis.json``.
    It replaces a stage plus a filename because those two are not enough:
    ingest, proxy, the quality report and movie-analysis.json all write outside a
    directory named after their stage, so a stage-scoped path had to be guessed
    and was wrong.
    """

    relative_path: str
    #: Recorded hash of the file, or None when the stage recorded none. None
    #: means the file is checked for existence only: claiming a hash comparison
    #: that was never recorded would report every such file as corrupt.
    expected_hash: str | None = None


@dataclass(frozen=True)
class IntegrityReport:
    """Result of scanning a job's artifacts."""

    job_id: str
    checked: int = 0
    ok: int = 0
    missing: list[str] = field(default_factory=list)
    corrupt: list[str] = field(default_factory=list)
    unsafe: list[str] = field(default_factory=list)
    #: Records that name no file, so nothing could be verified for them. Counted
    #: rather than folded into the failures: a row without a path is missing
    #: coverage, not a damaged file, and reporting it as a failure would send the
    #: operator looking for damage that is not there.
    unlocated: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.missing and not self.corrupt and not self.unsafe


def scan_job_integrity(
    jobs_dir: str | Path, job_id: str, records: list[ArtifactRecord]
) -> IntegrityReport:
    """Hash-verify each record under ``<jobs_dir>/<job_id>``.

    Paths are resolved through :func:`resolve_relative`, which validates every
    segment. Records naming a path outside the safe segment set are reported as
    ``unsafe`` rather than read: a tampered row must not be able to make the
    scanner hash arbitrary files on disk.
    """
    missing: list[str] = []
    corrupt: list[str] = []
    unsafe: list[str] = []
    ok = 0
    for record in records:
        label = record.relative_path
        try:
            path = resolve_relative(jobs_dir, job_id, label)
        except UnsafePathError:
            unsafe.append(label)
            continue
        if not path.is_file():
            missing.append(label)
            continue
        try:
            actual = sha256_file(path)
        except OSError:
            missing.append(label)
            continue
        if record.expected_hash is not None and actual != record.expected_hash:
            corrupt.append(label)
        else:
            ok += 1
    return IntegrityReport(
        job_id=job_id,
        checked=len(records),
        ok=ok,
        missing=missing,
        corrupt=corrupt,
        unsafe=unsafe,
    )


def verify_or_raise(
    jobs_dir: str | Path, job_id: str, records: list[ArtifactRecord]
) -> IntegrityReport:
    """Like :func:`scan_job_integrity` but raises on the first problem."""
    report = scan_job_integrity(jobs_dir, job_id, records)
    if report.unsafe:
        raise FileNotFoundError(f"Unsafe artifact paths for {job_id}: {report.unsafe}")
    if report.missing:
        raise FileNotFoundError(f"Missing artifacts for {job_id}: {report.missing}")
    if report.corrupt:
        first = report.corrupt[0]
        raise ArtifactIntegrityError(Path(first), "recorded", "mismatched")
    return report
