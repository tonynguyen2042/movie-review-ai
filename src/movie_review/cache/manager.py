"""Filesystem cache with integrity-checked lookup (T008).

Each entry is a ``<key>.bin`` payload plus a ``<key>.meta.json`` sidecar
recording the key and payload hash. Lookup is safe: a missing file, a key
mismatch, or a hash mismatch is a miss, and corrupt entries are removed so a
later store starts clean. All writes are atomic (T007).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from movie_review.artifacts import manager as artifacts

_BIN_SUFFIX = ".bin"
_META_SUFFIX = ".meta.json"


class CacheManager:
    """Content-keyed artifact cache rooted at ``cache_dir``."""

    def __init__(self, cache_dir: str | Path) -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _paths(self, key: str) -> tuple[Path, Path]:
        return self._dir / f"{key}{_BIN_SUFFIX}", self._dir / f"{key}{_META_SUFFIX}"

    def store(self, key: str, data: bytes) -> Path:
        """Atomically store payload bytes under ``key``; returns the payload path."""
        payload, meta = self._paths(key)
        artifacts.write_bytes(payload, data)
        artifacts.write_json(meta, {"key": key, "sha256": artifacts.sha256_bytes(data)})
        return payload

    def store_json(self, key: str, obj: Any) -> Path:
        """Atomically store a JSON-serializable object under ``key``."""
        return self.store(key, json.dumps(obj, sort_keys=True).encode("utf-8"))

    def lookup(self, key: str) -> Path | None:
        """Return the payload path on a verified hit, else ``None`` (miss).

        Corrupt entries (unreadable sidecar, key mismatch, hash mismatch) are
        removed and reported as a miss.
        """
        return self._verified(key)[0]

    def lookup_json(self, key: str) -> Any | None:
        """Return the parsed JSON payload on a verified hit, else ``None``.

        The payload is read once. It used to be read by the verification
        and then read again to parse it, so every cache hit read the file
        twice.
        """
        payload, data = self._verified(key)
        if payload is None or data is None:
            return None
        return json.loads(data)

    def _verified(self, key: str) -> tuple[Path | None, bytes | None]:
        """Read and verify a cache entry, returning the path and its bytes.

        The payload is read once and the digest is taken of what was read,
        rather than reading the file to hash it and then reading it again
        to parse it.
        """
        payload, meta = self._paths(key)
        try:
            record = artifacts.read_json(meta)
            if not isinstance(record, dict) or record.get("key") != key:
                raise artifacts.ArtifactIntegrityError(meta, key, "<key-mismatch>")
            data = payload.read_bytes()
            if hashlib.sha256(data).hexdigest() != str(record["sha256"]):
                raise artifacts.ArtifactIntegrityError(payload, key, "<hash-mismatch>")
        except (OSError, artifacts.ArtifactError, ValueError, KeyError, TypeError):
            self._remove(payload, meta)
            return None, None
        return payload, data

    def invalidate(self, key: str) -> bool:
        """Remove one entry; returns ``True`` when something was removed."""
        payload, meta = self._paths(key)
        return self._remove(payload, meta)

    def _remove(self, payload: Path, meta: Path) -> bool:
        removed = False
        for path in (payload, meta):
            try:
                path.unlink()
                removed = True
            except FileNotFoundError:
                continue
        return removed
