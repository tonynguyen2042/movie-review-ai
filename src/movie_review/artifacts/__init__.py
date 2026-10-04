"""Artifact paths, atomic writes, and integrity validation (T007)."""

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
    "UnsafePathError",
    "artifact_path",
    "manifest_path",
    "read_bytes",
    "read_json",
    "read_text",
    "sha256_bytes",
    "sha256_file",
    "verify",
    "write_bytes",
    "write_json",
    "write_text",
]
