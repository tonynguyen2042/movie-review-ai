"""Artifact provenance records (README section 72)."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field, PositiveInt


class Artifact(BaseModel):
    """One persisted stage output with full reproducibility metadata."""

    artifact_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    #: Path this record describes, relative to ``<jobs_dir>/<job_id>/`` -- for
    #: example ``scenes/scenes.json`` or ``media/media.json``. Recorded rather than
    #: reconstructed from ``stage``, because stages do not all write into a
    #: directory named after themselves. Optional only so rows written before
    #: schema 9 still load; validation reports those instead of guessing.
    relative_path: str | None = None
    version: PositiveInt = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    input_hash: str = Field(min_length=1)
    output_hash: str | None = None
    model: str | None = None
    prompt_version: str | None = None
