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
from movie_review.utils import logging as ulog
from movie_review.vision.port import AnalysisInput, VLMError, VLMPort, VLMUnavailableError
from movie_review.vision.qwen_vl import parse_analysis

CHAT_PATH = "/chat/completions"

#: Fallback completion budget when the profile does not set ``max_tokens``.
DEFAULT_MAX_TOKENS = 2048

#: How much of a bad reply to quote back in an error. Enough to recognise the
#: shape of the failure, short enough not to flood a log line.
EXCERPT_CHARS = 300

#: Appended on the second attempt, after the first reply could not be parsed.
RETRY_INSTRUCTION = (
    "\n\nYour previous reply could not be parsed. Reply with a single JSON "
    "object and nothing else: no prose, no explanation, no code fence."
)


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
        """Send frames plus prompt and return a validated analysis.

        Retries once when the reply cannot be parsed. The common cause is
        truncation at ``max_tokens``: the model opens the object, runs out of
        budget part-way through, and the half-written text is neither prose nor
        valid JSON. Failing the stage on that discards every scene already
        analysed -- for a feature film, most of an hour of VLM calls. The second
        attempt doubles the budget and restates the format.
        """
        if not analysis_input.frames:
            raise VLMError("Analysis requires at least one frame")
        for frame in analysis_input.frames:
            if not Path(frame).is_file():
                raise VLMError(f"Frame file not found: {frame}")
        if not prompt.strip():
            raise VLMError("Prompt must not be empty")

        url = http.build_endpoint(self._base_url, CHAT_PATH)
        budget = self._max_tokens
        last_error = "the model returned no usable reply"
        last_finish: str | None = None
        last_excerpt = ""

        for attempt in (1, 2):
            payload = {
                "model": self._model,
                "messages": self._messages(
                    analysis_input, prompt + RETRY_INSTRUCTION if attempt == 2 else prompt
                ),
                "temperature": self._temperature,
                "max_tokens": budget,
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
                # A transport failure is not a formatting problem; a second
                # attempt would only repeat it.
                raise VLMUnavailableError(self._model, str(exc)) from exc
            except http.RemoteProtocolError as exc:
                raise VLMError(str(exc)) from exc

            content, last_finish = _content_of(document, url)
            last_excerpt = ""
            exhausted = False

            if not content.strip():
                last_error = "the model returned an empty reply"
                last_excerpt = _excerpt(content)
            elif last_finish == "length":
                exhausted = True
                last_error = (
                    f"the reply was cut off at max_tokens={budget} "
                    "(finish_reason=length); raise max_tokens for this model in "
                    "the profile, or ask for shorter lists"
                )
                last_excerpt = _excerpt(content)
            else:
                try:
                    return parse_analysis(content, analysis_input.scene_id)
                except VLMError as exc:
                    # parse_analysis already quotes the reply it choked on;
                    # repeating it here would double every error message.
                    last_error = str(exc)

            if exhausted:
                # A bigger budget is the one thing that fixes truncation, so the
                # retry gets one. An unparseable-but-complete reply keeps the
                # budget: raising the ceiling cannot turn prose into JSON.
                budget *= 2

            ulog.get_logger("vision.remote").warning(
                "vlm.reply_unusable",
                extra={
                    "scene_id": analysis_input.scene_id,
                    "attempt": attempt,
                    "max_tokens": budget if exhausted else budget // 2,
                    "finish_reason": last_finish,
                    "reason": last_error,
                    "excerpt": last_excerpt or _excerpt(content),
                },
            )

        quoted = f"; last reply began: {last_excerpt!r}" if last_excerpt else ""
        raise VLMError(
            f"No usable analysis for {analysis_input.scene_id} after 2 attempts: "
            f"{last_error}. finish_reason={last_finish!r}{quoted}"
        )

    def unload(self) -> None:
        """No local weights are held; the remote host owns the model."""
        return None

    def available(self) -> bool:
        """True when the endpoint is configured well enough to attempt a call."""
        return bool(self._base_url and self._model)


def _excerpt(text: str) -> str:
    """A bounded, single-line view of a reply, for logs and error messages."""
    flattened = " ".join(text.split())
    if len(flattened) <= EXCERPT_CHARS:
        return flattened
    return flattened[:EXCERPT_CHARS] + "..."


def _content_of(document: Any, url: str) -> tuple[str, str | None]:
    """Pull the assistant text and the finish reason out of a chat response.

    ``finish_reason`` is not decoration: ``length`` is the only reliable signal
    that the reply was cut short, which is otherwise indistinguishable from a
    model that simply answered in prose.
    """
    if not isinstance(document, dict):
        raise VLMError(f"VLM response from {url} is not a JSON object")
    choices = document.get("choices")
    if not isinstance(choices, list) or not choices:
        raise VLMError(f"VLM response from {url} has no choices")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    content = message.get("content")
    if not isinstance(content, str):
        raise VLMError(f"VLM response from {url} has no message.content string")
    finish = choice.get("finish_reason")
    return content, finish if isinstance(finish, str) else None
