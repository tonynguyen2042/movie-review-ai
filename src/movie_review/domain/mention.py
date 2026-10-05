"""Character mention in dialogue or credits (discovery evidence, T028)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterMention(BaseModel):
    """One observed character reference with its source."""

    mention: str = Field(min_length=1)
    source_segment_id: str = Field(min_length=1)
    timestamp: float = Field(ge=0.0)
    character_id: str | None = None
