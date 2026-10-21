"""OpenAI-compatible remote reasoning adapter (remote-hosted local LLM).

Targets any server that speaks the OpenAI ``/chat/completions`` shape --
vLLM, llama.cpp's server, LM Studio, Ollama, TGI, or a plain reverse proxy
in front of one. This keeps a GPU box on the LAN or a home server out of the
orchestrating host while the pipeline still talks to the
:class:`~movie_review.reasoning.port.ReasoningPort` contract.

Implemented with :mod:`urllib` from the standard library so the project keeps
its small dependency set; no HTTP client is added.

Security notes:

* Credentials are never written to logs or error messages. Only the variable
  *name* is ever echoed.
* A user-supplied ``base_url`` is validated by
  :class:`~movie_review.config.settings.ModelSpec` to be an http(s) URL.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from movie_review.config.settings import GenerationSettings
from movie_review.reasoning.port import (
    ReasoningError,
    ReasoningPort,
    ReasoningUnavailableError,
)
from movie_review.remote import http

# Injected in tests; signature matches urllib.request.urlopen's callable subset.
RawTransport = Callable[..., Any]

DEFAULT_TIMEOUT_SECONDS = 120.0
_USER_AGENT = "movie-review-ai/0.1"


def build_chat_url(base_url: str) -> str:
    """Normalize a base URL to its ``/chat/completions`` endpoint."""
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"


class OpenAICompatAdapter(ReasoningPort):
    """Reasoning adapter for a remote OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        model: str,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = 2048,
        transport: RawTransport | None = None,
        system_prompt: str | None = None,
        generation: GenerationSettings | None = None,
    ) -> None:
        if not base_url:
            raise ReasoningError("base_url is required for a remote reasoning adapter")
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._max_tokens = max_tokens
        self._transport = transport
        self._system_prompt = system_prompt
        self._generation = generation or GenerationSettings()

    @property
    def model(self) -> str:
        """Configured model identity, as reported by the remote server."""
        return self._model

    @property
    def base_url(self) -> str:
        """Configured remote endpoint."""
        return self._base_url

    def _payload(self, prompt: str, temperature: float) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        messages.append({"role": "user", "content": prompt})
        return {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            # The seed and the top-p are what make a run reproducible.
            "seed": self._generation.seed,
            "top_p": self._generation.top_p,
            "max_tokens": self._max_tokens,
            # Ask for JSON when we can; extract_json_output still tolerates prose.
            "stream": False,
        }

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def complete(self, prompt: str, *, temperature: float | None = None) -> str:
        """POST one chat completion and return the assistant text.

        The request goes through the shared transport, so it reuses a pooled
        connection and retries a transient failure. The adapter used to carry
        its own copy of the request logic, so the two paths drifted and the
        reasoning one got neither.
        """
        if not prompt.strip():
            raise ReasoningError("Prompt must not be empty")

        url = build_chat_url(self._base_url)
        payload = self._payload(
            prompt,
            self._generation.temperature if temperature is None else temperature,
        )

        try:
            document = http.post_json(
                url,
                payload,
                api_key=self._api_key,
                timeout=self._timeout,
                transport=self._transport,
            )
        except http.RemoteUnavailableError as exc:
            raise ReasoningUnavailableError(self._model, str(exc)) from exc
        except http.RemoteProtocolError as exc:
            raise ReasoningError(str(exc)) from exc

        return self._extract_text(document, url)

    def _extract_text(self, document: Any, url: str) -> str:
        """Pull ``choices[0].message.content`` out of the response body."""
        choices = document.get("choices") if isinstance(document, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ReasoningError(f"Remote reasoning response from {url} has no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str):
            raise ReasoningError(
                f"Remote reasoning response from {url} has no message.content string"
            )
        return content

    def unload(self) -> None:
        """No local resources to release; the remote server owns the weights."""
        return None

    def available(self) -> bool:
        """True when the endpoint is configured well enough to attempt a call."""
        return bool(self._base_url and self._model)
