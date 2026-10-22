"""The remote profile has to name the routes the servers actually serve.

A trial run against a real remote host found the ASR slot pointing at
`/v1/audio/transcriptions` -- the OpenAI-compatible route -- while the
server on the other end is a whisper.cpp server, which serves
`/inference`. A request to the OpenAI route came back 404 and the
transcript stage never ran.

The route is configuration, so it can be wrong. This pins the two things
that have to agree: the base URL and the path.
"""

from __future__ import annotations

import pytest

from movie_review.config.settings import load_settings
from movie_review.remote import http


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch):
    """The remote profile, with nothing overriding it."""
    for var in list(__import__("os").environ):
        if var.startswith("MOVIE_REVIEW_"):
            monkeypatch.delenv(var, raising=False)
    return load_settings(profile="remote")


def test_the_asr_slot_names_the_route_the_server_serves(remote) -> None:
    """The whisper.cpp server serves /inference."""
    asr = remote.models.asr
    assert asr.endpoint_path == "/inference"
    assert asr.base_url.endswith(":9000")
    assert "/v1" not in asr.base_url, (
        "the base URL must not carry the /v1 prefix the server does not have"
    )


def test_the_asr_adapter_posts_to_the_route_the_spec_names(remote) -> None:
    """The spec decides where the request goes."""
    from movie_review.asr.factory import build_asr_adapter

    asr = remote.models.asr.model_copy(update={"cloud_ai": True})
    adapter = build_asr_adapter(asr)
    # The route is an adapter detail, so the port does not declare it.
    route = getattr(adapter, "endpoint_path", None)
    assert route == "/inference"
    assert http.build_endpoint(asr.base_url, route) == ("http://192.168.1.144:9000/inference")


def test_the_other_remote_slots_keep_the_openai_route(remote) -> None:
    """The LLM slots are OpenAI-compatible servers; only the ASR is not."""
    for name in ("vision", "reasoning", "tts"):
        slot = getattr(remote.models, name)
        assert slot.base_url.endswith("/v1"), name
        assert slot.endpoint_path is None, name
