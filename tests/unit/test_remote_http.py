"""The transport must reuse connections and retry a transient failure.

T136 regression. `urllib.request.urlopen` sets `Connection: close` on every
request (CPython's `urllib/request.py`), so each of the roughly 2000 model
calls a 2 h run makes paid a fresh TCP and TLS handshake. And there was no
retry at all: `perform` raised on the first `URLError` or `HTTPError`, so a
single blip aborted a run that had been going for hours.

The reasoning adapter carried its own copy of the request logic, so the two
paths drifted and the reasoning one got neither.
"""

from __future__ import annotations

import json
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from movie_review.remote import http


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _request(url: str = "http://gpu:8000/v1/chat/completions") -> Request:
    return Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")


def test_a_transient_failure_is_retried() -> None:
    """A 5xx must be tried again before it is reported."""
    attempts: list[int] = []

    def transport(request: Any, timeout: float) -> _FakeResponse:
        attempts.append(1)
        if len(attempts) < 3:
            raise HTTPError("http://gpu:8000/v1/chat/completions", 503, "busy", Message(), None)
        return _FakeResponse(b'{"ok": true}')

    body = http.perform(
        _request(), 60.0, transport, url="http://gpu:8000/v1/chat/completions", backoff_seconds=0
    )
    assert body == b'{"ok": true}'
    assert len(attempts) == 3


def test_a_rate_limit_is_retried() -> None:
    attempts: list[int] = []

    def transport(request: Any, timeout: float) -> _FakeResponse:
        attempts.append(1)
        if len(attempts) < 2:
            raise HTTPError(
                "http://gpu:8000/v1/chat/completions", 429, "slow down", Message(), None
            )
        return _FakeResponse(b"{}")

    http.perform(
        _request(), 60.0, transport, url="http://gpu:8000/v1/chat/completions", backoff_seconds=0
    )
    assert len(attempts) == 2


def test_a_client_error_is_not_retried() -> None:
    """A 400 is the request's own fault; repeating it wastes the server."""
    attempts: list[int] = []

    def transport(request: Any, timeout: float) -> _FakeResponse:
        attempts.append(1)
        raise HTTPError("http://gpu:8000/v1/chat/completions", 400, "bad request", Message(), None)

    try:
        http.perform(
            _request(),
            60.0,
            transport,
            url="http://gpu:8000/v1/chat/completions",
            backoff_seconds=0,
        )
    except http.RemoteProtocolError as exc:
        assert "400" in str(exc)
    else:
        raise AssertionError("a 400 must be reported")
    assert len(attempts) == 1, "a 400 was retried"


def test_a_connection_failure_is_retried() -> None:
    attempts: list[int] = []

    def transport(request: Any, timeout: float) -> _FakeResponse:
        attempts.append(1)
        if len(attempts) < 2:
            raise URLError("connection refused")
        return _FakeResponse(b"{}")

    http.perform(
        _request(), 60.0, transport, url="http://gpu:8000/v1/chat/completions", backoff_seconds=0
    )
    assert len(attempts) == 2


def test_a_persistent_failure_is_reported_after_the_attempts() -> None:
    attempts: list[int] = []

    def transport(request: Any, timeout: float) -> _FakeResponse:
        attempts.append(1)
        raise HTTPError("http://gpu:8000/v1/chat/completions", 500, "boom", Message(), None)

    try:
        http.perform(
            _request(),
            60.0,
            transport,
            url="http://gpu:8000/v1/chat/completions",
            attempts=3,
            backoff_seconds=0,
        )
    except http.RemoteProtocolError:
        pass
    else:
        raise AssertionError("a persistent failure must be reported")
    assert len(attempts) == 3


def test_a_timeout_is_reported_as_unavailable() -> None:
    """A timeout must map to the unavailable error, not a raw TimeoutError."""

    def transport(request: Any, timeout: float) -> _FakeResponse:
        raise TimeoutError

    try:
        http.perform(
            _request(),
            60.0,
            transport,
            url="http://gpu:8000/v1/chat/completions",
            attempts=1,
            backoff_seconds=0,
        )
    except http.RemoteUnavailableError:
        pass
    else:
        raise AssertionError("a timeout must be reported as unavailable")


def test_the_backoff_grows_and_is_bounded() -> None:
    """The delay must grow with the attempt and stay under the cap."""
    delays = [http._backoff_delay(attempt, 0.5) for attempt in range(1, 12)]
    assert all(delay >= 0 for delay in delays)
    assert max(delays) <= 30.0
    # The first attempt's delay is around the base; later ones are larger.
    assert delays[-1] > delays[0]


def test_the_pool_reuses_one_connection_per_host() -> None:
    """Two requests to one host must share a connection."""
    pool = http._Pool()
    sent: list[str] = []

    class _FakeConnection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            self.host = host

        def request(self, method: str, path: str, body: Any, headers: Any) -> None:
            sent.append(f"{method} {path}")

        def getresponse(self) -> Any:
            class _Response:
                status = 200

                def read(self) -> bytes:
                    return b"{}"

            return _Response()

        def close(self) -> None:
            return None

    # The module object, so the pool's factory can be swapped for the test.
    import importlib

    module = importlib.import_module("movie_review.remote.http")
    original = module.HTTPConnection
    module.HTTPConnection = _FakeConnection  # type: ignore[attr-defined]
    try:
        pool.send(_request("http://gpu:8000/v1/chat/completions"), 60.0)
        pool.send(_request("http://gpu:8000/v1/chat/completions"), 60.0)
    finally:
        module.HTTPConnection = original  # type: ignore[attr-defined]

    assert len(sent) == 2
    assert len(pool._connections) == 1, "a second connection was opened for the same host"
    pool.close()
    assert pool._connections == {}


def test_the_reasoning_adapter_uses_the_shared_transport() -> None:
    """The reasoning adapter must not carry its own request logic."""
    from movie_review.reasoning.openai_compat import OpenAICompatAdapter

    calls: list[str] = []

    def transport(request: Any, timeout: float) -> _FakeResponse:
        calls.append(request.full_url)
        return _FakeResponse(
            json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode("utf-8")
        )

    adapter = OpenAICompatAdapter("m", "http://gpu:8000/v1", transport=transport)
    assert adapter.complete("prompt") == "hello"
    assert calls == ["http://gpu:8000/v1/chat/completions"]
