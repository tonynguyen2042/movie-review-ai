"""The record of one model invocation (README sections 52 and 53).

Every model call is recorded: the model, the runtime, the stage, the
prompt's hash, the tokens it cost, how long it took and the temperature it
ran at. README §53 calls this "essential for reproducibility" -- without it
there is no way to answer "what produced this?" about a job that is already
finished.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, PositiveInt


class ModelUsage(BaseModel):
    """The tokens one model call cost.

    A local runtime often cannot report this, so both counts are optional:
    a missing count means "not reported", not "zero".
    """

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class ModelRun(BaseModel):
    """One recorded model invocation."""

    run_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    model: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    prompt_hash: str = ""
    prompt_version: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    temperature: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: PositiveInt = 1
