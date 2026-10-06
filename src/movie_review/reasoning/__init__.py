"""Reasoning LLM ports and adapters (T033 shared prerequisite)."""

from movie_review.reasoning.factory import build_reasoning_adapter
from movie_review.reasoning.openai_compat import OpenAICompatAdapter, build_chat_url
from movie_review.reasoning.port import (
    ReasoningError,
    ReasoningPort,
    ReasoningUnavailableError,
    extract_json_output,
)
from movie_review.reasoning.qwen import QwenReasoningAdapter

__all__ = [
    "OpenAICompatAdapter",
    "QwenReasoningAdapter",
    "ReasoningError",
    "ReasoningPort",
    "ReasoningUnavailableError",
    "build_chat_url",
    "build_reasoning_adapter",
    "extract_json_output",
]
