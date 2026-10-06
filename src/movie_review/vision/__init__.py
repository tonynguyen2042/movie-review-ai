"""Vision-language ports, adapters, and stages (T022-T025)."""

from movie_review.vision.analysis import (
    VisualAnalysisError,
    VisualAnalysisResult,
    previous_summary,
    run_visual_analysis,
    scene_dialogue,
)
from movie_review.vision.factory import build_vlm_adapter
from movie_review.vision.openai_compat import OpenAICompatVLMAdapter
from movie_review.vision.port import AnalysisInput, VLMError, VLMPort, VLMUnavailableError
from movie_review.vision.qwen_vl import QwenVLAdapter, parse_analysis

__all__ = [
    "AnalysisInput",
    "OpenAICompatVLMAdapter",
    "QwenVLAdapter",
    "VLMError",
    "VLMUnavailableError",
    "VLMPort",
    "VisualAnalysisError",
    "VisualAnalysisResult",
    "build_vlm_adapter",
    "parse_analysis",
    "previous_summary",
    "run_visual_analysis",
    "scene_dialogue",
]
