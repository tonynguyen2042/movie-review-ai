"""VLM adapter selection from a model spec."""

from __future__ import annotations

from movie_review.config.settings import ModelSpec
from movie_review.vision.openai_compat import DEFAULT_MAX_TOKENS, OpenAICompatVLMAdapter
from movie_review.vision.port import VLMPort
from movie_review.vision.qwen_vl import QwenVLAdapter


def build_vlm_adapter(spec: ModelSpec, *, max_tokens: int | None = None) -> VLMPort:
    """Build the vision adapter described by ``spec``.

    ``max_tokens`` overrides the profile; otherwise ``spec.max_tokens`` applies,
    falling back to :data:`DEFAULT_MAX_TOKENS`. The override stays for callers
    that pass it explicitly (tests, benchmarks).
    """
    if not spec.enabled:
        raise ValueError(f"Vision model {spec.model!r} is disabled")
    if spec.is_remote:
        assert spec.base_url is not None  # guaranteed by ModelSpec validation
        return OpenAICompatVLMAdapter(
            spec.model,
            spec.base_url,
            api_key=spec.resolved_api_key(),
            timeout_seconds=spec.timeout_seconds,
            max_tokens=max_tokens or spec.max_tokens or DEFAULT_MAX_TOKENS,
        )
    return QwenVLAdapter(spec.model)
