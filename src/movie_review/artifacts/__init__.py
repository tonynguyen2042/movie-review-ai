"""Artifact paths, atomic writes, and integrity validation (T007, T073 scan)."""

from movie_review.artifacts.integrity import (
    ArtifactRecord,
    IntegrityReport,
    scan_job_integrity,
    verify_or_raise,
)
from movie_review.artifacts.manager import (
    ArtifactError,
    ArtifactIntegrityError,
    UnsafePathError,
    artifact_path,
    manifest_path,
    read_bytes,
    read_json,
    read_text,
    sha256_bytes,
    sha256_file,
    verify,
    write_bytes,
    write_json,
    write_text,
)

__all__ = [
    "ArtifactError",
    "ArtifactIntegrityError",
    "ArtifactRecord",
    "IntegrityReport",
    "UnsafePathError",
    "artifact_path",
    "manifest_path",
    "read_bytes",
    "read_json",
    "read_text",
    "scan_job_integrity",
    "sha256_bytes",
    "sha256_file",
    "verify",
    "verify_or_raise",
    "write_bytes",
    "write_json",
    "write_text",
]
