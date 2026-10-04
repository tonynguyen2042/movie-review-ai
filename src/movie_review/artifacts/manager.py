"""Deterministic artifact paths, hashes, atomic writes, integrity (T007).

Layout follows plan.md section 4: ``<jobs_dir>/<job_id>/<stage>/<file>``.
Stage names are free-form (future pipeline stages); only the layout shape and
the manifest location are fixed here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

_MANIFEST_FILENAME = "manifest.json"
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


class ArtifactError(Exception):
    """Base class for artifact failures."""


class UnsafePathError(ArtifactError):
    """A job/stage/filename segment could escape the artifact root."""


class ArtifactIntegrityError(ArtifactError):
    """Stored bytes do not match their recorded hash."""

    def __init__(self, path: Path, expected: str, actual: str) -> None:
        super().__init__(f"Integrity check failed for {path}: expected {expected}, got {actual}")
        self.path = path
        self.expected = expected
        self.actual = actual


def _safe_segment(value: str, kind: str) -> str:
    if not _SAFE_SEGMENT.fullmatch(value):
        raise UnsafePathError(f"Unsafe {kind} segment: {value!r}")
    return value


def artifact_path(jobs_dir: str | Path, job_id: str, stage: str, filename: str) -> Path:
    """Deterministic path for one artifact; rejects traversal outside the root."""
    _safe_segment(job_id, "job")
    _safe_segment(stage, "stage")
    _safe_segment(filename, "file")
    return Path(jobs_dir) / job_id / stage / filename


def manifest_path(jobs_dir: str | Path, job_id: str) -> Path:
    """Deterministic path of a job's ``manifest.json``."""
    _safe_segment(job_id, "job")
    return Path(jobs_dir) / job_id / _MANIFEST_FILENAME


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Hex SHA-256 of a file, streamed in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 64), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bytes(path: str | Path, data: bytes) -> str:
    """Atomically write bytes (tmp file + fsync + rename); returns hex hash."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return sha256_bytes(data)


def write_text(path: str | Path, text: str) -> str:
    """Atomically write UTF-8 text; returns hex hash."""
    return write_bytes(path, text.encode("utf-8"))


def write_json(path: str | Path, obj: Any) -> str:
    """Atomically write canonical JSON (sorted keys); returns hex hash."""
    return write_bytes(path, json.dumps(obj, sort_keys=True).encode("utf-8"))


def verify(path: str | Path, expected_hash: str) -> Path:
    """Raise :class:`ArtifactIntegrityError` unless the file matches its hash."""
    resolved = Path(path)
    actual = sha256_file(resolved)
    if actual != expected_hash:
        raise ArtifactIntegrityError(resolved, expected_hash, actual)
    return resolved


def read_bytes(path: str | Path, expected_hash: str | None = None) -> bytes:
    """Read bytes, optionally verifying integrity first."""
    if expected_hash is not None:
        verify(path, expected_hash)
    with open(path, "rb") as f:
        return f.read()


def read_text(path: str | Path, expected_hash: str | None = None) -> str:
    """Read UTF-8 text, optionally verifying integrity first."""
    return read_bytes(path, expected_hash).decode("utf-8")


def read_json(path: str | Path, expected_hash: str | None = None) -> Any:
    """Read JSON, optionally verifying integrity first."""
    return json.loads(read_text(path, expected_hash))
