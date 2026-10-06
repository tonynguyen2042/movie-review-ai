"""ASR adapter selection from a model spec."""

from __future__ import annotations

from movie_review.asr.openai_compat import OpenAICompatASRAdapter
from movie_review.asr.port import ASRPort
from movie_review.asr.whisper_mlx import WhisperMLXAdapter
from movie_review.config.settings import ModelSpec


def build_asr_adapter(spec: ModelSpec) -> ASRPort:
    """Build the ASR adapter described by ``spec``."""
    if not spec.enabled:
        raise ValueError(f"ASR model {spec.model!r} is disabled")
    if spec.is_remote:
        assert spec.base_url is not None  # guaranteed by ModelSpec validation
        return OpenAICompatASRAdapter(
            spec.model,
            spec.base_url,
            api_key=spec.resolved_api_key(),
            timeout_seconds=spec.timeout_seconds,
        )
    return WhisperMLXAdapter(spec.model)
