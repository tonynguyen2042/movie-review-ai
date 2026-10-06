"""VLM port: model-agnostic scene visual understanding contract (T022, P6).

Adapters (Qwen3-VL in T023, fakes in tests) implement :class:`VLMPort`.
Prompt text and versioning belong to T024; this contract only executes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from movie_review.domain.scene_analysis import SceneAnalysis


class VLMError(Exception):
    """Base class for visual understanding failures."""


class VLMUnavailableError(VLMError):
    """The configured VLM or runtime cannot be loaded here."""

    def __init__(self, model: str, detail: str = "") -> None:
        message = f"VLM unavailable: {model}"
        if detail:
            message += f": {detail}"
        super().__init__(message)
        self.model = model


@dataclass
class AnalysisInput:
    """One scene analysis request: frames plus story context (spec section 15)."""

    scene_id: str
    frames: list[Path] = field(default_factory=list)
    dialogue: str = ""
    previous_summary: str | None = None


class VLMPort(ABC):
    """Keyframe-to-structure visual understanding (spec section 15)."""

    @property
    def model(self) -> str:
        """Model identity used in cache keys.

        See :attr:`movie_review.asr.port.ASRPort.model` -- stages read this
        rather than checking adapter types, so a remote VLM contributes its
        real model id to cache identity instead of its class name.
        """
        return type(self).__name__

    @abstractmethod
    def analyze(self, analysis_input: AnalysisInput, prompt: str) -> SceneAnalysis:
        """Analyze frames with a caller-rendered prompt; never invents schema."""

    @abstractmethod
    def unload(self) -> None:
        """Release model resources (memory strategy, plan section 6)."""
