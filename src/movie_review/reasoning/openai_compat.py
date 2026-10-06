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

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from movie_review.reasoning.port import (
    ReasoningError,
    ReasoningPort,
    ReasoningUnavailableError,
)

# Injected in tests; signature matches urllib.request.urlopen's callable subset.
RawTransport = Callable[..., Any]

DEFAULT_TIMEOUT_SECONDS = 120.0
_USER_AGENT = "movie-review-ai/0.1"


def _default_transport(request: Request, timeout: float) -> Any:
    """Perform the HTTP POST via urllib."""
    return urlopen(request, timeout=timeout)  # noqa: S310 - scheme validated upstream


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

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        """POST one chat completion and return the assistant text."""
        if not prompt.strip():
            raise ReasoningError("Prompt must not be empty")

        url = build_chat_url(self._base_url)
        body = json.dumps(self._payload(prompt, temperature)).encode("utf-8")
        request = Request(url, data=body, headers=self._headers(), method="POST")

        transport = self._transport or _default_transport
        try:
            with transport(request, self._timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            # Never echo the request headers: they carry the bearer token.
            raise ReasoningError(f"Remote reasoning endpoint returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise ReasoningUnavailableError(
                self._model, f"cannot reach {url}: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise ReasoningUnavailableError(
                self._model, f"request to {url} timed out after {self._timeout}s"
            ) from exc

        return self._extract_text(raw, url)

    def _extract_text(self, raw: bytes | str, url: str) -> str:
        """Pull ``choices[0].message.content`` out of the response body."""
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ReasoningError(
                    f"Remote reasoning endpoint returned non-UTF-8 body from {url}"
                ) from exc
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            preview = raw[:200].replace("\n", " ")
            raise ReasoningError(
                f"Remote reasoning endpoint returned invalid JSON from {url}: {preview}"
            ) from exc

        choices = document.get("choices")
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
