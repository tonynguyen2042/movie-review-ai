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
import random
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

# Injected in tests; matches the subset of urlopen's signature we rely on.
RawTransport = Callable[..., Any]

DEFAULT_TIMEOUT_SECONDS = 120.0
#: How many times a transient failure is retried before it is reported.
DEFAULT_ATTEMPTS = 3
#: The base of the exponential backoff between retries, in seconds.
DEFAULT_BACKOFF_SECONDS = 0.5
#: The ceiling for a single backoff sleep. A schedule that keeps doubling
#: without one would turn a long outage into an unbounded wait.
DEFAULT_MAX_BACKOFF_SECONDS = 30.0
#: How much of an error response is quoted back in the message. A server
#: that answers 500 usually says why in the body -- an engine failure, a
#: context that is too long -- and that sentence is the difference between
#: diagnosing the failure and guessing at it.
ERROR_EXCERPT_CHARS = 300
#: How many idle connections are kept per host. One is enough for a
#: sequential run; the vision stage analyses eight scenes per batch, so the
#: pool has to be able to lend more than one at a time. The cap keeps a burst
#: from leaving a socket per burst thread open for the life of the process.
_MAX_IDLE_PER_HOST = 8
_USER_AGENT = "movie-review-ai/0.1"


@dataclass(frozen=True)
class TransportRetry:
    """How long one HTTP request keeps trying before the adapter hears about it.

    The configuration layer owns these numbers (``ModelSpec.attempts`` and
    friends) because what is long enough depends on the host: a whisper.cpp
    box that answers in two seconds and a vLLM engine that needs a minute to
    reload after a crash want different schedules. The defaults match the
    behaviour the transport had when the values were literals.

    Distinct from :class:`movie_review.pipeline.retry.RetryPolicy`, which
    decides how many times a whole *stage* is re-run.
    """

    #: Total attempts, not retries: 3 means the first try plus two more.
    attempts: int = DEFAULT_ATTEMPTS
    #: Base of the exponential backoff between attempts, in seconds. Zero
    #: disables the wait entirely, which is what a test wants.
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS
    #: Ceiling for one sleep; the schedule grows to this and stops.
    max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS


DEFAULT_RETRY = TransportRetry()


class RemoteUnavailableError(Exception):
    """The remote host is unreachable, timed out, or could not serve the request.

    A 5xx ends up here rather than in :class:`RemoteProtocolError`: the request
    was well formed and the host failed to answer it, which is the same class
    of problem as a refused connection and deserves the same retry.
    """


class RemoteProtocolError(Exception):
    """The remote host answered, but the answer is not usable.

    A 4xx lands here -- the request itself is at fault, so repeating it only
    wastes the server's time -- as does a body that cannot be decoded.
    """


class _Permanent(Exception):
    """A failure that another attempt will not fix."""

    def __init__(self, public: Exception) -> None:
        super().__init__(str(public))
        self.public = public


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


class _Transient(Exception):
    """A failure worth retrying, with the exception to raise if it persists."""

    def __init__(self, public: Exception) -> None:
        super().__init__(str(public))
        self.public = public


def _is_retryable_status(code: int) -> bool:
    """Whether an HTTP status is worth another attempt.

    A 4xx other than 429 is the request's own fault: a bad body, a bad
    model name, a missing key. Repeating it wastes the server's time. A 5xx
    or a rate limit is the server's, and another attempt usually succeeds --
    the vision stage lost a twenty-minute run to one 500 that a longer wait
    would have survived.
    """
    return code == 429 or 500 <= code < 600


def _error_excerpt(body: bytes) -> str:
    """A bounded, single-line view of an error response body.

    The pool and the transport read the body anyway, so an error status used
    to throw away the one sentence the server wrote about what went wrong.
    """
    flattened = " ".join(body.decode("utf-8", errors="replace").split())
    if len(flattened) <= ERROR_EXCERPT_CHARS:
        return flattened
    return flattened[:ERROR_EXCERPT_CHARS] + "..."


def _status_failure(status: int, url: str, body: bytes) -> _Transient | _Permanent:
    """An error status as the wrapper that decides whether to try again.

    A retryable status (429, a 5xx) maps to :class:`RemoteUnavailableError`:
    the request was fine and the host failed to serve it, so the retry counts
    against the transport budget and the adapters report it as a model that
    was momentarily unavailable rather than one that answered badly. Anything
    else is the request's own fault and is not repeated.
    """
    excerpt = _error_excerpt(body)
    detail = f"HTTP {status} from {url}" + (f": {excerpt}" if excerpt else "")
    if _is_retryable_status(status):
        return _Transient(RemoteUnavailableError(detail))
    return _Permanent(RemoteProtocolError(detail))


class _Pool:
    """Keep-alive connections, lent one at a time.

    ``urllib.request.urlopen`` sets ``Connection: close`` on every request
    (CPython's ``urllib/request.py``), so each of the roughly 2000 model
    calls a 2 h run makes paid a fresh TCP and TLS handshake.

    One connection per host was enough while the pipeline was sequential.
    The vision stage analyses four scenes at once, and an ``HTTPConnection``
    carries one request at a time: two threads sharing the pooled connection
    made the second raise ``CannotSendRequest('Request-sent')``, a
    client-side state error that was reported as "cannot reach <url>" and
    sent the operator looking at a server that was answering perfectly well.
    The idle connections of a host are therefore kept in a list and checked
    out to one caller at a time, with a fresh connection created when none is
    free.
    """

    def __init__(self) -> None:
        self._idle: dict[tuple[str, str, int], list[Any]] = {}
        self._lock = threading.Lock()

    def _acquire(
        self, key: tuple[str, str, int], scheme: str, host: str, port: int, timeout: float
    ) -> Any:
        """An idle connection for this host, or a new one when none is free."""
        with self._lock:
            bucket = self._idle.get(key)
            if bucket:
                return bucket.pop()
        factory = HTTPSConnection if scheme == "https" else HTTPConnection
        return factory(host, port, timeout=timeout)

    def _release(self, key: tuple[str, str, int], connection: Any) -> None:
        """Return a healthy connection to the idle list, or close the surplus."""
        with self._lock:
            bucket = self._idle.setdefault(key, [])
            if len(bucket) < _MAX_IDLE_PER_HOST:
                bucket.append(connection)
                return
        _close_quietly(connection)

    def send(self, request: Request, timeout: float) -> bytes:
        """Send the request over a connection only this call holds."""
        parsed = urlsplit(request.full_url)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or ""
        port = parsed.port or (443 if scheme == "https" else 80)
        key = (scheme, host, port)

        connection = self._acquire(key, scheme, host, port, timeout)

        path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        try:
            connection.request(
                request.get_method(),
                path,
                body=request.data,
                headers=dict(request.header_items()),
            )
            response = connection.getresponse()
            body = response.read()
            status = response.status
        except (OSError, HTTPException) as exc:
            # The connection belongs to this call, not to the pool, so it is
            # closed rather than removed: a half-used socket never goes back
            # to the idle list. The next attempt opens a fresh one.
            _close_quietly(connection)
            raise _Transient(
                RemoteUnavailableError(f"cannot reach {request.full_url}: {exc}")
            ) from exc

        # The body is read in full, so the connection is reusable even when
        # the status is an error: a 5xx is the server's answer, not a broken
        # socket.
        self._release(key, connection)
        if status >= 400:
            raise _status_failure(status, request.full_url, body)
        return body if isinstance(body, bytes) else str(body).encode("utf-8")

    def close(self) -> None:
        """Close every idle connection."""
        with self._lock:
            idle = [connection for bucket in self._idle.values() for connection in bucket]
            self._idle.clear()
        for connection in idle:
            _close_quietly(connection)


def _close_quietly(connection: Any) -> None:
    """Close a connection, ignoring a socket the peer already closed."""
    try:
        connection.close()
    except OSError:
        pass


#: The process-wide pool. Every caller shares it, and the stages that run
#: their scenes concurrently (vision, events) each get a connection of their
#: own for the duration of a request.
_POOL = _Pool()


def _backoff_delay(attempt: int, base: float, cap: float = DEFAULT_MAX_BACKOFF_SECONDS) -> float:
    """Exponential backoff with jitter, capped.

    The jitter matters: without it, a server that fails a whole batch at
    once receives the whole batch again at the same instant. The cap matters
    for the opposite reason: an engine that needs a minute to come back must
    not be hammered with a sleep that has doubled past any useful wait.
    """
    if base <= 0:
        return 0.0
    ceiling = max(cap, base)
    delay: float = min(base * (2 ** (attempt - 1)), ceiling) * (0.5 + random.random() / 2)
    return delay


def perform(
    request: Request,
    timeout: float,
    transport: RawTransport | None = None,
    *,
    url: str,
    retry: TransportRetry = DEFAULT_RETRY,
) -> bytes:
    """Execute the request and return the raw body.

    A transient failure -- a refused connection, a timeout, a 5xx or a rate
    limit -- is retried with exponential backoff, up to ``retry.attempts``
    attempts in total. The previous behaviour raised on the first one, so a
    single blip aborted a run that had been going for hours.

    Raises:
        RemoteUnavailableError: connection refused, DNS failure, timeout, or
            a retryable status the host kept answering with.
        RemoteProtocolError: a status the request itself caused (4xx).
    """
    attempts = max(1, retry.attempts)
    last: _Transient | None = None
    for attempt in range(1, attempts + 1):
        try:
            if transport is not None:
                return _perform_once(request, timeout, transport, url=url)
            return _POOL.send(request, timeout)
        except _Transient as exc:
            last = exc
            if attempt < attempts:
                delay = _backoff_delay(attempt, retry.backoff_seconds, retry.max_backoff_seconds)
                if delay:
                    time.sleep(delay)
        except _Permanent as exc:
            raise exc.public from exc
    assert last is not None
    raise last.public


def _error_body(error: HTTPError) -> bytes:
    """The body of an HTTP error response, when the transport carried one.

    ``HTTPError`` is file-like over the response it wraps, so the server's
    own explanation of the failure is available here -- and was discarded.
    """
    try:
        body = error.read()
    except (OSError, ValueError, AttributeError):
        # Some transports (and every test double built with a stub fp) expose
        # no readable body; the status alone is still worth reporting.
        return b""
    return body if isinstance(body, bytes) else b""


def _perform_once(request: Request, timeout: float, transport: RawTransport, *, url: str) -> bytes:
    """One request through an injected transport."""
    try:
        with transport(request, timeout) as response:
            body = response.read()
    except HTTPError as exc:
        # Never echo headers: they carry the bearer token. The body is the
        # server's own words and is quoted bounded by _status_failure.
        raise _status_failure(exc.code, url, _error_body(exc)) from exc
    except URLError as exc:
        raise _Transient(RemoteUnavailableError(f"cannot reach {url}: {exc.reason}")) from exc
    except TimeoutError as exc:
        raise _Transient(
            RemoteUnavailableError(f"request to {url} timed out after {timeout}s")
        ) from exc
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
    retry: TransportRetry = DEFAULT_RETRY,
) -> Any:
    """POST a JSON body and return the decoded JSON response."""
    headers = auth_headers(api_key)
    request = Request(
        url,
        data=json.dumps(dict(payload)).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    return decode_json(perform(request, timeout, transport, url=url, retry=retry), url)


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
    retry: TransportRetry = DEFAULT_RETRY,
) -> bytes:
    """POST a multipart body and return the raw response."""
    body, content_type = encode_multipart(fields, files)
    headers = auth_headers(api_key, json_body=False)
    headers["Content-Type"] = content_type
    request = Request(url, data=body, headers=headers, method="POST")
    return perform(request, timeout, transport, url=url, retry=retry)


def post_for_bytes(
    url: str,
    payload: Mapping[str, Any],
    *,
    api_key: str | None,
    timeout: float,
    transport: RawTransport | None = None,
    retry: TransportRetry = DEFAULT_RETRY,
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
    return perform(request, timeout, transport, url=url, retry=retry)
