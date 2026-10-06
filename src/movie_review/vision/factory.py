"""VLM adapter selection from a model spec."""

from __future__ import annotations

from movie_review.config.settings import ModelSpec
from movie_review.vision.openai_compat import OpenAICompatVLMAdapter
from movie_review.vision.port import VLMPort
from movie_review.vision.qwen_vl import QwenVLAdapter


def build_vlm_adapter(spec: ModelSpec, *, max_tokens: int = 2048) -> VLMPort:
    """Build the vision adapter described by ``spec``."""
    if not spec.enabled:
        raise ValueError(f"Vision model {spec.model!r} is disabled")
    if spec.is_remote:
        assert spec.base_url is not None  # guaranteed by ModelSpec validation
        return OpenAICompatVLMAdapter(
            spec.model,
            spec.base_url,
            api_key=spec.resolved_api_key(),
            timeout_seconds=spec.timeout_seconds,
            max_tokens=max_tokens,
        )
    return QwenVLAdapter(spec.model)
