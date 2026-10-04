"""Cache identity computation (T008, spec section 55).

A cache key binds every input that can change an artifact: content hashes,
code/prompt versions, model identity, and generation config. Identical work
must reuse artifacts; any change must miss.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field


class CacheSpec(BaseModel):
    """Everything a cached artifact depends on."""

    stage: str = Field(min_length=1)
    stage_version: str = Field(min_length=1)
    input_hash: str = Field(min_length=1)
    dependency_hashes: dict[str, str] = Field(default_factory=dict)
    model_id: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    generation_config: dict[str, Any] = Field(default_factory=dict)


def cache_key(spec: CacheSpec) -> str:
    """Hex SHA-256 over the canonical (key-sorted) JSON of the spec."""
    canonical = json.dumps(spec.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
