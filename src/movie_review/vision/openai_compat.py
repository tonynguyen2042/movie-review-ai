"""Remote VLM adapter for OpenAI-compatible vision chat endpoints.

Targets any server exposing ``POST /chat/completions`` with OpenAI-style
multimodal content parts (vLLM, LM Studio, llama.cpp server, Ollama, TGI).
Frames are inlined as base64 ``image_url`` data URIs, so the orchestrating host
needs neither the MLX vision runtime nor the weights.

Output parsing reuses :func:`movie_review.vision.qwen_vl.parse_analysis`, so
schema validation, the "caller's scene_id always wins" rule, and tolerance for
prose/fenced JSON are identical to the local path.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from movie_review.domain.scene_analysis import SceneAnalysis
from movie_review.remote import http
from movie_review.vision.port import AnalysisInput, VLMError, VLMPort, VLMUnavailableError
from movie_review.vision.qwen_vl import parse_analysis

CHAT_PATH = "/chat/completions"


def encode_frame(path: str | Path) -> str:
    """Encode one image file as a ``data:`` URI for an ``image_url`` part."""
    resolved = Path(path)
    mime = mimetypes.guess_type(resolved.name)[0] or "image/jpeg"
    encoded = base64.b64encode(resolved.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


class OpenAICompatVLMAdapter(VLMPort):
    """Scene analysis against a remote OpenAI-compatible vision endpoint."""

    def __init__(
        self,
        model: str,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = http.DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = 2048,
        temperature: float = 0.4,
        transport: http.RawTransport | None = None,
    ) -> None:
        if not base_url:
            raise VLMError("base_url is required for a remote VLM adapter")
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._transport = transport

    @property
    def model(self) -> str:
        """Configured model identity."""
        return self._model

    @property
    def base_url(self) -> str:
        """Configured remote endpoint."""
        return self._base_url

    def _messages(self, analysis_input: AnalysisInput, prompt: str) -> list[dict[str, Any]]:
        """Build multimodal messages: images first, then the caller's prompt."""
        parts: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": encode_frame(frame)}}
            for frame in analysis_input.frames
        ]
        parts.append({"type": "text", "text": prompt})
        return [{"role": "user", "content": parts}]

    def analyze(self, analysis_input: AnalysisInput, prompt: str) -> SceneAnalysis:
        """Send frames plus prompt and return a validated analysis."""
        if not analysis_input.frames:
            raise VLMError("Analysis requires at least one frame")
        for frame in analysis_input.frames:
            if not Path(frame).is_file():
                raise VLMError(f"Frame file not found: {frame}")
        if not prompt.strip():
            raise VLMError("Prompt must not be empty")

        url = http.build_endpoint(self._base_url, CHAT_PATH)
        payload = {
            "model": self._model,
            "messages": self._messages(analysis_input, prompt),
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": False,
        }
        try:
            document = http.post_json(
                url,
                payload,
                api_key=self._api_key,
                timeout=self._timeout,
                transport=self._transport,
            )
        except http.RemoteUnavailableError as exc:
            raise VLMUnavailableError(self._model, str(exc)) from exc
        except http.RemoteProtocolError as exc:
            raise VLMError(str(exc)) from exc

        return parse_analysis(_content_of(document, url), analysis_input.scene_id)

    def unload(self) -> None:
        """No local weights are held; the remote host owns the model."""
        return None

    def available(self) -> bool:
        """True when the endpoint is configured well enough to attempt a call."""
        return bool(self._base_url and self._model)


def _content_of(document: Any, url: str) -> str:
    """Pull the assistant text out of a chat-completions response."""
    if not isinstance(document, dict):
        raise VLMError(f"VLM response from {url} is not a JSON object")
    choices = document.get("choices")
    if not isinstance(choices, list) or not choices:
        raise VLMError(f"VLM response from {url} has no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str):
        raise VLMError(f"VLM response from {url} has no message.content string")
    return content
