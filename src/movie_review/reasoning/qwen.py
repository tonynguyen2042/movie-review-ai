"""Qwen reasoning adapter implementing :class:`ReasoningPort` (T033).

Lazy MLX loading; tests and non-MLX hosts inject a ``backend`` callable.
Model identity comes from the caller (configured ``models.reasoning``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from movie_review.config.settings import GenerationSettings
from movie_review.reasoning.port import (
    ReasoningError,
    ReasoningPort,
    ReasoningUnavailableError,
)

RawBackend = Callable[[str, float], str]


def _load_mlx_backend(model: str, max_tokens: int) -> RawBackend:
    """Build the real MLX backend or raise :class:`ReasoningUnavailableError`.

    NOTE: the ``mlx_lm`` call shape must be verified on Apple hardware during
    model benchmarking (T074); offline hosts always take the injected path.
    """
    try:
        from mlx_lm import generate, load  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ReasoningUnavailableError(model, "mlx-lm is not installed") from exc
    try:
        loaded_model, tokenizer = load(model)
    except Exception as exc:
        raise ReasoningUnavailableError(model, f"cannot load weights: {exc}") from exc

    def _complete(prompt: str, temperature: float) -> str:
        try:
            raw = generate(
                loaded_model,
                tokenizer,
                prompt=prompt,
                max_tokens=max_tokens,
                temp=temperature,
                verbose=False,
            )
        except Exception as exc:
            raise ReasoningError(f"Reasoning failed: {exc}") from exc
        return cast("str", raw)

    return _complete


class QwenReasoningAdapter(ReasoningPort):
    """Qwen reasoning family via MLX (model name supplied by caller)."""

    def __init__(
        self,
        model: str,
        backend: RawBackend | None = None,
        max_tokens: int = 2048,
        generation: GenerationSettings | None = None,
    ) -> None:
        self._model = model
        self._backend = backend
        self._max_tokens = max_tokens
        self._generation = generation or GenerationSettings()

    @property
    def model(self) -> str:
        """Configured model identity."""
        return self._model

    def _ensure_loaded(self) -> RawBackend:
        if self._backend is None:
            self._backend = _load_mlx_backend(self._model, self._max_tokens)
        return self._backend

    def complete(self, prompt: str, *, temperature: float | None = None) -> str:
        if not prompt.strip():
            raise ReasoningError("Prompt must not be empty")
        return self._ensure_loaded()(
            prompt,
            self._generation.temperature if temperature is None else temperature,
        )

    def unload(self) -> None:
        """Drop the backend so its memory can be reclaimed (plan section 6)."""
        self._backend = None
        try:
            import mlx.core as mx  # type: ignore[import-not-found]

            mx.clear_cache()
        except ImportError:
            pass
