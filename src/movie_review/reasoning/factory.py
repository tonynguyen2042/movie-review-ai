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

#: The completion budget when neither the caller nor the profile names one.
#: A scene's event array routinely outgrows a short budget, and a truncated
#: reply is an unparsable one, so the floor sits where a full reply fits.
DEFAULT_MAX_TOKENS = 2048


def build_reasoning_adapter(spec: ModelSpec, *, max_tokens: int | None = None) -> ReasoningPort:
    """Build the reasoning adapter described by ``spec``.

    ``max_tokens`` overrides the profile; otherwise ``spec.max_tokens``
    applies, falling back to :data:`DEFAULT_MAX_TOKENS`. The same resolution
    the vision factory uses -- before it, a ``max_tokens`` set in the
    configuration was a no-op for reasoning calls (T186).

    Raises:
        ValueError: if the spec is disabled or its endpoint settings are
            incomplete (already validated by :class:`ModelSpec`).
    """
    if not spec.enabled:
        raise ValueError(f"Reasoning model {spec.model!r} is disabled")
    require_cloud_ai(spec, spec.cloud_ai, "reasoning")
    resolved = max_tokens or spec.max_tokens or DEFAULT_MAX_TOKENS

    if spec.is_remote:
        assert spec.base_url is not None  # guaranteed by ModelSpec validation
        return OpenAICompatAdapter(
            spec.model,
            spec.base_url,
            api_key=spec.resolved_api_key(),
            timeout_seconds=spec.timeout_seconds,
            retry=spec.retry,
            max_tokens=resolved,
            generation=spec.generation,
        )

    return QwenReasoningAdapter(spec.model, max_tokens=resolved, generation=spec.generation)
