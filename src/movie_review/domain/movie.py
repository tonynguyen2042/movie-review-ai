"""Movie ingest metadata (spec FR-001; README section 9)."""

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt


class MovieMetadata(BaseModel):
    """Validated media facts extracted at ingest."""

    file: str
    sha256: str = Field(min_length=64, max_length=64)
    duration_seconds: PositiveFloat
    width: PositiveInt
    height: PositiveInt
    fps: PositiveFloat
    video_codec: str
    audio_codec: str | None = None
    container: str | None = None


class Movie(BaseModel):
    """A movie under analysis."""

    id: str = Field(min_length=1)
    metadata: MovieMetadata
