"""Adapter selection from a model spec (keeps model choice out of call sites).

Call sites ask for "the reasoning adapter for this profile" and get either
the local MLX adapter or the remote OpenAI-compatible one, based on
``ModelSpec.backend``.
"""

from __future__ import annotations

from movie_review.config.settings import ModelSpec, require_cloud_ai
from movie_review.reasoning.openai_compat import OpenAICompatAdapter
from movie_review.reasoning.port import ReasoningPort
from movie_review.reasoning.qwen import QwenReasoningAdapter


def build_reasoning_adapter(spec: ModelSpec, *, max_tokens: int = 2048) -> ReasoningPort:
    """Build the reasoning adapter described by ``spec``.

    Raises:
        ValueError: if the spec is disabled or its endpoint settings are
            incomplete (already validated by :class:`ModelSpec`).
    """
    if not spec.enabled:
        raise ValueError(f"Reasoning model {spec.model!r} is disabled")
    require_cloud_ai(spec, spec.cloud_ai, "reasoning")

    if spec.is_remote:
        assert spec.base_url is not None  # guaranteed by ModelSpec validation
        return OpenAICompatAdapter(
            spec.model,
            spec.base_url,
            api_key=spec.resolved_api_key(),
            timeout_seconds=spec.timeout_seconds,
            max_tokens=max_tokens,
        )

    return QwenReasoningAdapter(spec.model, max_tokens=max_tokens)
