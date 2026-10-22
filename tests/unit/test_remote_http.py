"""The shared HTTP transport needs its own tests.

T165. `remote/http.py` is 211 lines and had **no direct test**. The adapters
that use it exercised it indirectly, but its own branches did not run:
`build_endpoint`, `auth_headers`, the `TimeoutError` branch of `perform`,
the error branches of `decode_json`, `encode_multipart`, `file_upload` and
the two `post_*` helpers were never called directly.

The `TimeoutError` branch matters most: a hung remote server raised a raw
`TimeoutError` instead of `RemoteUnavailableError`, which broke the error
contract every adapter relies on.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from http.client import CannotSendRequest
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

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


# --- the endpoint --------------------------------------------------------


def test_build_endpoint_joins_the_path() -> None:
    assert http.build_endpoint("http://gpu:8000/v1", "/chat/completions") == (
        "http://gpu:8000/v1/chat/completions"
    )


def test_build_endpoint_tolerates_a_trailing_slash() -> None:
    assert http.build_endpoint("http://gpu:8000/v1/", "/chat/completions") == (
        "http://gpu:8000/v1/chat/completions"
    )


def test_build_endpoint_is_idempotent() -> None:
    """A base that already ends with the path is not doubled."""
    assert http.build_endpoint("http://gpu:8000/v1/chat/completions", "/chat/completions") == (
        "http://gpu:8000/v1/chat/completions"
    )


def test_build_endpoint_adds_the_leading_slash() -> None:
    assert http.build_endpoint("http://gpu:8000/v1", "chat/completions") == (
        "http://gpu:8000/v1/chat/completions"
    )


# --- the headers ---------------------------------------------------------


def test_auth_headers_omit_the_token_when_there_is_none() -> None:
    headers = http.auth_headers(None)
    assert "Authorization" not in headers
    assert headers["Content-Type"] == "application/json"


def test_auth_headers_carry_the_bearer_token() -> None:
    headers = http.auth_headers("secret")
    assert headers["Authorization"] == "Bearer secret"


def test_auth_headers_omit_the_content_type_for_a_multipart_body() -> None:
    """A multipart body sets its own content type, with the boundary."""
    headers = http.auth_headers("secret", json_body=False)
    assert "Content-Type" not in headers


# --- the error mapping ---------------------------------------------------


def test_a_timeout_maps_to_unavailable() -> None:
    """A hung server must not raise a raw TimeoutError.

    Every adapter catches `RemoteUnavailableError`; a raw TimeoutError
    escaped all of them.
    """

    def transport(request: Any, timeout: float) -> _FakeResponse:
        raise TimeoutError

    with pytest.raises(http.RemoteUnavailableError):
        http.perform(
            Request("http://gpu:8000/v1", data=b"{}", method="POST"),
            60.0,
            transport,
            url="http://gpu:8000/v1",
            attempts=1,
        )


def test_a_refused_connection_maps_to_unavailable() -> None:
    def transport(request: Any, timeout: float) -> _FakeResponse:
        raise URLError("connection refused")

    with pytest.raises(http.RemoteUnavailableError, match="cannot reach"):
        http.perform(
            Request("http://gpu:8000/v1", data=b"{}", method="POST"),
            60.0,
            transport,
            url="http://gpu:8000/v1",
            attempts=1,
        )


def test_an_http_error_maps_to_a_protocol_error() -> None:
    def transport(request: Any, timeout: float) -> _FakeResponse:
        raise HTTPError("http://gpu:8000/v1", 404, "not found", Message(), None)

    with pytest.raises(http.RemoteProtocolError, match="404"):
        http.perform(
            Request("http://gpu:8000/v1", data=b"{}", method="POST"),
            60.0,
            transport,
            url="http://gpu:8000/v1",
            attempts=1,
        )


def test_the_error_message_never_carries_the_token() -> None:
    """The headers carry the bearer token; the message must not."""

    def transport(request: Any, timeout: float) -> _FakeResponse:
        raise HTTPError("http://gpu:8000/v1", 500, "boom", Message(), None)

    with pytest.raises(http.RemoteProtocolError) as excinfo:
        http.perform(
            Request("http://gpu:8000/v1", data=b"{}", method="POST"),
            60.0,
            transport,
            url="http://gpu:8000/v1",
            attempts=1,
        )
    assert "secret" not in str(excinfo.value)


# --- the body decoding ---------------------------------------------------


def test_decode_json_reads_an_object() -> None:
    assert http.decode_json(b'{"ok": true}', "http://gpu") == {"ok": True}


def test_decode_json_reports_invalid_json() -> None:
    with pytest.raises(http.RemoteProtocolError, match="invalid JSON"):
        http.decode_json(b"not json", "http://gpu")


def test_decode_json_reports_a_non_utf8_body() -> None:
    with pytest.raises(http.RemoteProtocolError, match="non-UTF-8"):
        http.decode_json(b"\xff\xfe", "http://gpu")


# --- the multipart body --------------------------------------------------


def test_encode_multipart_carries_the_fields_and_the_file(tmp_path: Path) -> None:
    body, content_type = http.encode_multipart(
        {"model": "whisper"},
        {"file": ("audio.wav", b"\x00\x01", "audio/wav")},
    )
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="model"' in body
    assert b"whisper" in body
    assert b'name="file"; filename="audio.wav"' in body
    assert b"audio/wav" in body


def test_encode_multipart_sanitises_the_filename() -> None:
    """A path in the filename must not travel into the request."""
    body, _ = http.encode_multipart(
        {}, {"file": ("../../etc/passwd", b"\x00", "application/octet-stream")}
    )
    assert b"passwd" in body
    assert b"../" not in body


def test_file_upload_guesses_the_content_type(tmp_path: Path) -> None:
    path = tmp_path / "audio.wav"
    path.write_bytes(b"\x00")
    name, content, content_type = http.file_upload(path)
    assert name == "audio.wav"
    assert content == b"\x00"
    assert content_type in ("audio/wav", "audio/x-wav")


def test_file_upload_falls_back_for_an_unknown_type(tmp_path: Path) -> None:
    path = tmp_path / "thing.unknown"
    path.write_bytes(b"\x00")
    _, _, content_type = http.file_upload(path)
    assert content_type == "application/octet-stream"


# --- the posting helpers -------------------------------------------------


def test_post_json_sends_the_payload() -> None:
    seen: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> _FakeResponse:
        seen["body"] = request.data
        seen["url"] = request.full_url
        return _FakeResponse(b'{"ok": true}')

    document = http.post_json(
        "http://gpu:8000/v1/chat/completions",
        {"model": "m", "messages": []},
        api_key="secret",
        timeout=60.0,
        transport=transport,
    )
    assert document == {"ok": True}
    assert json.loads(seen["body"]) == {"model": "m", "messages": []}


def test_post_for_bytes_returns_the_raw_body() -> None:
    def transport(request: Any, timeout: float) -> _FakeResponse:
        return _FakeResponse(b"\x00\x01")

    body = http.post_for_bytes(
        "http://gpu:8000/v1/tts",
        {"text": "hello"},
        api_key=None,
        timeout=60.0,
        transport=transport,
    )
    assert body == b"\x00\x01"


def test_post_multipart_uploads_the_file() -> None:
    seen: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> _FakeResponse:
        seen["body"] = request.data
        return _FakeResponse(b"{}")

    http.post_multipart(
        "http://gpu:9000/v1/audio/transcriptions",
        {"model": "whisper"},
        {"file": ("audio.wav", b"\x00", "audio/wav")},
        api_key=None,
        timeout=60.0,
        transport=transport,
    )
    assert b'name="file"; filename="audio.wav"' in seen["body"]


# --- the connection pool -------------------------------------------------


class _PoolResponse:
    """The slice of ``http.client.HTTPResponse`` the pool reads."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body


class _FakeConnection:
    """A stand-in for ``HTTPConnection`` that one message can drive at a time.

    Real ``http.client`` connections raise ``CannotSendRequest('Request-sent')``
    when a second caller sends while a response is still pending -- that is the
    failure a shared pool produced for the vision stage -- so the fake does too.
    """

    #: Every fake connection created, oldest first.
    created: list[_FakeConnection] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.closed = False
        self.requests = 0
        self.body: bytes = b"{}"
        self.status: int = 200
        self.fail_with: Exception | None = None
        self._in_flight = False
        _FakeConnection.created.append(self)

    # -- http.client's interface, as far as the pool uses it --------------

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        if self._in_flight:
            raise CannotSendRequest("Request-sent")
        if self.fail_with is not None:
            raise self.fail_with
        self._in_flight = True
        self.requests += 1
        # Hold the connection long enough that the other threads reach the
        # pool while this request is still in flight.
        time.sleep(0.05)

    def getresponse(self) -> _PoolResponse:
        self._in_flight = False
        return _PoolResponse(self.body, self.status)

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[_FakeConnection]]:
    """Route ``http.HTTPConnection`` to the fake and start from an empty pool."""
    http._POOL.close()
    _FakeConnection.created = []
    monkeypatch.setattr(http, "HTTPConnection", _FakeConnection)
    yield _FakeConnection.created
    http._POOL.close()


def _pooled_post(attempts: int = 3) -> bytes:
    return http.perform(
        Request("http://gpu:8000/v1", data=b"{}", method="POST"),
        60.0,
        None,
        url="http://gpu:8000/v1",
        attempts=attempts,
    )


def test_concurrent_calls_do_not_share_one_connection(
    fake_connections: list[_FakeConnection],
) -> None:
    """The vision stage runs four scenes at once; they must not share a socket.

    Before T176 every caller took the same pooled ``HTTPConnection``, so the
    second thread raised ``CannotSendRequest('Request-sent')`` and the run died
    with "cannot reach <url>" against a healthy server.
    """
    start = threading.Barrier(4)

    def call() -> None:
        start.wait(timeout=5)
        _pooled_post(attempts=1)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(call) for _ in range(4)]
        for future in futures:
            future.result()

    assert len(fake_connections) == 4
    assert all(connection.requests == 1 for connection in fake_connections)


def test_a_sequential_call_reuses_the_pooled_connection(
    fake_connections: list[_FakeConnection],
) -> None:
    """Keep-alive survives the thread-safe pool: one call at a time is cheap."""
    for _ in range(3):
        _pooled_post()

    assert len(fake_connections) == 1
    assert fake_connections[0].requests == 3


def test_a_broken_connection_is_closed_and_replaced(
    fake_connections: list[_FakeConnection], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A socket the peer closed is not put back into the idle list."""

    def broken(*args: Any, **kwargs: Any) -> _FakeConnection:
        connection = _FakeConnection(*args, **kwargs)
        connection.fail_with = ConnectionResetError("reset by peer")
        return connection

    monkeypatch.setattr(http, "HTTPConnection", broken)

    with pytest.raises(http.RemoteUnavailableError, match="cannot reach"):
        _pooled_post(attempts=1)

    assert fake_connections[0].closed is True

    monkeypatch.setattr(http, "HTTPConnection", _FakeConnection)
    _pooled_post()

    assert len(fake_connections) == 2


def test_an_error_status_keeps_the_connection(
    fake_connections: list[_FakeConnection], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 5xx is the server's answer, not a dead socket: the connection is reused."""

    def failing_host(*args: Any, **kwargs: Any) -> _FakeConnection:
        connection = _FakeConnection(*args, **kwargs)
        connection.status = 500
        return connection

    monkeypatch.setattr(http, "HTTPConnection", failing_host)

    with pytest.raises(http.RemoteProtocolError, match="500"):
        _pooled_post(attempts=1)
    assert fake_connections[0].closed is False

    with pytest.raises(http.RemoteProtocolError, match="500"):
        _pooled_post(attempts=1)

    assert len(fake_connections) == 1


def test_close_closes_the_idle_connections(
    fake_connections: list[_FakeConnection],
) -> None:
    _pooled_post()
    http._POOL.close()
    assert fake_connections[0].closed is True
