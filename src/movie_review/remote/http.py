"""Shared HTTP transport for remote (non-MLX) model endpoints.

Single place for the urllib plumbing used by the ASR, VLM, reasoning, and TTS
remote adapters, so request/error handling is identical across ports. The
project has no HTTP client dependency; :mod:`urllib` from the standard library
keeps it that way.

Error mapping is deliberately left to each adapter: the ports define distinct
hierarchies (``ASRError``/``ModelUnavailableError``, ``VLMError``, ``TTSError``,
``ReasoningError``) and callers match on those. These two exceptions are the
transport-level vocabulary that adapters translate from.
"""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Injected in tests; matches the subset of urlopen's signature we rely on.
RawTransport = Callable[..., Any]

DEFAULT_TIMEOUT_SECONDS = 120.0
_USER_AGENT = "movie-review-ai/0.1"


class RemoteUnavailableError(Exception):
    """The remote host is unreachable, timed out, or refused the connection."""


class RemoteProtocolError(Exception):
    """The remote host answered, but not with a usable response."""


def build_endpoint(base_url: str, path: str) -> str:
    """Join a base URL with an API path, tolerating trailing slashes.

    A base that already ends with the requested path is returned unchanged, so
    ``http://host/v1`` and ``http://host/v1/chat/completions`` both work.
    """
    trimmed = base_url.rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    if trimmed.endswith(suffix):
        return trimmed
    return f"{trimmed}{suffix}"


def auth_headers(api_key: str | None, *, json_body: bool = True) -> dict[str, str]:
    """Standard headers, with a bearer token when one is configured."""
    headers = {
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _urlopen(request: Request, timeout: float) -> Any:
    """Typed wrapper so :func:`urlopen` matches the transport signature.

    ``timeout`` must be a keyword on the stdlib overloads once ``data`` is
    supplied, but transports (including test doubles) are called with it
    positionally; this keeps both sides type-clean without ignores.
    """
    return urlopen(request, timeout=timeout)  # noqa: S310 - scheme validated upstream


def perform(
    request: Request,
    timeout: float,
    transport: RawTransport | None = None,
    *,
    url: str,
) -> bytes:
    """Execute the request and return the raw body.

    Raises:
        RemoteUnavailableError: connection refused, DNS failure, or timeout.
        RemoteProtocolError: a non-2xx HTTP status.
    """
    call = transport or _urlopen
    try:
        with call(request, timeout) as response:
            body = response.read()
    except HTTPError as exc:
        # Never echo headers: they carry the bearer token.
        raise RemoteProtocolError(f"HTTP {exc.code} from {url}") from exc
    except URLError as exc:
        raise RemoteUnavailableError(f"cannot reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RemoteUnavailableError(f"request to {url} timed out after {timeout}s") from exc
    return body if isinstance(body, bytes) else str(body).encode("utf-8")


def decode_json(body: bytes, url: str) -> Any:
    """Decode a JSON body, reporting a truncated preview on failure."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RemoteProtocolError(f"non-UTF-8 response body from {url}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        preview = text[:200].replace("\n", " ")
        raise RemoteProtocolError(f"invalid JSON from {url}: {preview}") from exc


def post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    api_key: str | None,
    timeout: float,
    transport: RawTransport | None = None,
) -> Any:
    """POST a JSON body and return the decoded JSON response."""
    headers = auth_headers(api_key)
    request = Request(
        url,
        data=json.dumps(dict(payload)).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    return decode_json(perform(request, timeout, transport, url=url), url)


def encode_multipart(
    fields: Mapping[str, str],
    files: Mapping[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    """Encode ``multipart/form-data``.

    Args:
        fields: plain form fields.
        files: ``field name -> (filename, content, content type)``.

    Returns:
        ``(body, content_type)`` where content_type carries the boundary.
    """
    boundary = f"----movie-review-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    for name, (filename, content, content_type) in files.items():
        safe_name = os.path.basename(filename)
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{safe_name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n".encode()
        )
        parts.append(content)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def file_upload(path: str | Path) -> tuple[str, bytes, str]:
    """Read a file into a ``(filename, content, content type)`` triple."""
    resolved = Path(path)
    guessed = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    return resolved.name, resolved.read_bytes(), guessed


def post_multipart(
    url: str,
    fields: Mapping[str, str],
    files: Mapping[str, tuple[str, bytes, str]],
    *,
    api_key: str | None,
    timeout: float,
    transport: RawTransport | None = None,
) -> bytes:
    """POST a multipart body and return the raw response."""
    body, content_type = encode_multipart(fields, files)
    headers = auth_headers(api_key, json_body=False)
    headers["Content-Type"] = content_type
    request = Request(url, data=body, headers=headers, method="POST")
    return perform(request, timeout, transport, url=url)


def post_for_bytes(
    url: str,
    payload: Mapping[str, Any],
    *,
    api_key: str | None,
    timeout: float,
    transport: RawTransport | None = None,
) -> bytes:
    """POST a JSON body and return the raw (possibly binary) response."""
    headers = auth_headers(api_key, json_body=False)
    headers["Content-Type"] = "application/json"
    request = Request(
        url,
        data=json.dumps(dict(payload)).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    return perform(request, timeout, transport, url=url)
