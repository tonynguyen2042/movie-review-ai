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


def relative_artifact_path(jobs_dir: str | Path, job_id: str, path: str | Path) -> str:
    """``path`` expressed relative to the job root, for recording.

    Stages do not all write into a directory named after themselves -- ingest and
    proxy both write into ``media/``, the quality report into ``qc/``, and
    movie-analysis.json sits at the job root. Recording the path that was
    actually written, rather than a stage name plus a guessed filename, is what
    lets validation find the file instead of reconstructing where it should be.
    """
    root = Path(jobs_dir) / _safe_segment(job_id, "job")
    resolved = Path(path)
    try:
        relative = resolved.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise UnsafePathError(f"{resolved} is not inside the job root {root}") from exc
    return relative.as_posix()


def resolve_relative(jobs_dir: str | Path, job_id: str, relative: str) -> Path:
    """Resolve a recorded relative path; rejects anything escaping the job root.

    Every segment is validated, so a tampered row cannot make a validator read
    an arbitrary file on disk. An absolute path or a ``..`` segment fails here
    rather than being normalised away.
    """
    root = Path(jobs_dir) / _safe_segment(job_id, "job")
    # An absolute path is a tampered row. It has to fail here rather than be
    # reinterpreted: dropping the leading separator would turn
    # "/etc/passwd" into "<root>/etc/passwd", which stays inside the root
    # but reads a file the row never named.
    if relative.startswith("/") or relative.startswith("\\"):
        raise UnsafePathError(f"Absolute artifact path: {relative!r}")
    # A Windows drive path is the same thing.
    if len(relative) > 1 and relative[1] == ":":
        raise UnsafePathError(f"Absolute artifact path: {relative!r}")
    segments = [segment for segment in relative.split("/") if segment]
    if not segments:
        raise UnsafePathError("Empty artifact path")
    for segment in segments:
        _safe_segment(segment, "path")
    return root.joinpath(*segments)


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()


#: The digest of a file, keyed by its path, size and modification time.
#: A file that has not changed cannot have a different digest.
_FILE_HASHES: dict[tuple[str, int, int], str] = {}


def sha256_file(path: str | Path) -> str:
    """Hex SHA-256 of a file, streamed in chunks.

    The digest is memoised by path, size and modification time. The source
    movie and the analysis proxy were hashed six times across the pipeline
    -- about 13-15 GB of redundant reads for a 2 h film -- and a file that
    has not changed cannot have a different digest.
    """
    resolved = Path(path)
    try:
        stat = resolved.stat()
    except OSError:
        stat = None
    if stat is not None:
        key = (str(resolved), stat.st_size, stat.st_mtime_ns)
        cached = _FILE_HASHES.get(key)
        if cached is not None:
            return cached
    else:
        key = None

    digest = hashlib.sha256()
    with open(resolved, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 64), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    if key is not None:
        _FILE_HASHES[key] = value
    return value


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
