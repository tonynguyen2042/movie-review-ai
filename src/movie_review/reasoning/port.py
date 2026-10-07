"""Reasoning LLM port: model-agnostic text completion contract (T033, P6).

First needed by event extraction; shared by all later reasoning stages
(T036-T038, T041+). Model identity comes from the caller (configured
``models.reasoning``); the runtime loads lazily (NFR-006).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any


class ReasoningError(Exception):
    """Base class for reasoning failures."""


class ReasoningUnavailableError(ReasoningError):
    """The configured reasoning model or runtime cannot be loaded here."""

    def __init__(self, model: str, detail: str = "") -> None:
        message = f"Reasoning model unavailable: {model}"
        if detail:
            message += f": {detail}"
        super().__init__(message)
        self.model = model


def extract_json_output(text: str) -> Any:
    """Parse model output as JSON, tolerating surrounding prose or fences."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ReasoningError("Model output contains no JSON value")


class ReasoningPort(ABC):
    """Text completion with structured-output helpers."""

    @property
    def model(self) -> str:
        """Model identity recorded in artifacts and cache keys.

        Concrete adapters override it with the configured checkpoint. See
        :attr:`movie_review.asr.port.ASRPort.model` for why this is part of the
        contract rather than something callers should reach for by type check.
        """
        return type(self).__name__

    @abstractmethod
    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        """Complete a prompt with raw model text."""

    def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
        """Complete and parse the output as JSON."""
        return extract_json_output(self.complete(prompt, temperature=temperature))

    @abstractmethod
    def unload(self) -> None:
        """Release model resources (memory strategy, plan section 6)."""
