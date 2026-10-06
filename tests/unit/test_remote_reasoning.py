"""T-NEW: remote (OpenAI-compatible) reasoning endpoint configuration and adapter."""

import json
from typing import Any

import pytest
import yaml

from movie_review.config.settings import ModelSpec, load_settings
from movie_review.reasoning import (
    OpenAICompatAdapter,
    ReasoningError,
    ReasoningPort,
    ReasoningUnavailableError,
    build_chat_url,
    build_reasoning_adapter,
    extract_json_output,
)

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


class FakeResponse:
    """Minimal stand-in for the object urlopen returns."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _ok_body(content: str = '{"answer": 42}') -> bytes:
    return json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": content}}]}
    ).encode()


def _settings_dir(tmp_path, profile: dict, selected: str = "remote") -> Any:
    (tmp_path / "models.yaml").write_text(
        yaml.safe_dump({"profiles": {"remote": profile}}), encoding="utf-8"
    )
    (tmp_path / "default.yaml").write_text(
        yaml.safe_dump(
            {
                "models": {"profile": selected},
                "prompts": {"versions": {"scene_analysis": "v1"}},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def _profile(**reasoning: Any) -> dict:
    return {
        "asr": {"model": "whisper-large-v3-turbo"},
        "vision": {"model": "qwen3-vl"},
        "reasoning": reasoning,
        "critic": {"model": "qwen3.5", "enabled": False},
        "tts": {"model": "qwen3-tts"},
    }


# --------------------------------------------------------------------------
# configuration schema
# --------------------------------------------------------------------------


def test_default_backend_is_mlx_and_local() -> None:
    """Existing configs keep the historical MLX behaviour."""
    spec = ModelSpec(model="Qwen3.5-27B")
    assert spec.backend == "mlx"
    assert spec.is_remote is False
    assert spec.base_url is None
    assert spec.timeout_seconds == 120.0


def test_remote_spec_loads_from_yaml(tmp_path) -> None:
    """A remote profile resolves endpoint settings from models.yaml."""
    d = _settings_dir(
        tmp_path,
        _profile(
            model="qwen3.5-27b",
            backend="openai_compatible",
            base_url="http://gpu-box.lan:8000/v1",
            timeout_seconds=300.0,
        ),
    )
    settings = load_settings(config_path=d / "default.yaml", models_path=d / "models.yaml")
    spec = settings.models.reasoning

    assert settings.models.profile == "remote"
    assert spec.is_remote is True
    assert spec.base_url == "http://gpu-box.lan:8000/v1"
    assert spec.timeout_seconds == 300.0
    assert spec.model == "qwen3.5-27b"


def test_remote_profile_selected_by_env_var(tmp_path, monkeypatch) -> None:
    """Profile selection works without editing default.yaml."""
    d = _settings_dir(
        tmp_path,
        _profile(model="qwen3.5-27b", backend="openai_compatible", base_url="http://gpu:8000/v1"),
    )
    monkeypatch.setenv("MOVIE_REVIEW_MODELS__PROFILE", "remote")
    settings = load_settings(config_path=d / "default.yaml", models_path=d / "models.yaml")
    assert settings.models.profile == "remote"
    assert settings.models.reasoning.is_remote is True


def test_remote_backend_requires_base_url() -> None:
    """A remote backend without an endpoint fails fast at load time."""
    with pytest.raises(ValueError, match="requires base_url"):
        ModelSpec(model="m", backend="openai_compatible")


def test_base_url_must_be_http_scheme() -> None:
    """Non-http schemes are rejected rather than attempted."""
    with pytest.raises(ValueError, match="http://"):
        ModelSpec(model="m", backend="openai_compatible", base_url="ftp://host/v1")


def test_unknown_backend_is_rejected() -> None:
    """A typo in backend fails loudly."""
    with pytest.raises(ValueError, match="Unknown backend"):
        ModelSpec(model="m", backend="openai-compat")


def test_api_key_read_from_named_env_var(monkeypatch) -> None:
    """api_key_env names the variable; the key never sits in YAML."""
    monkeypatch.setenv("MY_LLM_TOKEN", "secret-token")
    spec = ModelSpec(
        model="m",
        backend="openai_compatible",
        base_url="http://gpu:8000/v1",
        api_key_env="MY_LLM_TOKEN",
    )
    assert spec.resolved_api_key() == "secret-token"


def test_api_key_absent_when_env_var_not_configured() -> None:
    """No api_key_env means no credential lookup."""
    assert ModelSpec(model="m").resolved_api_key() is None


def test_missing_api_key_env_fails_loudly(monkeypatch) -> None:
    """A named-but-unset variable fails instead of sending anonymous calls."""
    monkeypatch.delenv("ABSENT_TOKEN", raising=False)
    spec = ModelSpec(
        model="m",
        backend="openai_compatible",
        base_url="http://gpu:8000/v1",
        api_key_env="ABSENT_TOKEN",
    )
    with pytest.raises(ValueError, match="ABSENT_TOKEN"):
        spec.resolved_api_key()


def test_secret_is_not_stored_on_the_spec(monkeypatch) -> None:
    """The spec exposes the key only through the resolver, not as a field."""
    monkeypatch.setenv("MY_LLM_TOKEN", "secret-token")
    spec = ModelSpec(model="m", api_key_env="MY_LLM_TOKEN")
    assert "secret-token" not in spec.model_dump_json()
    assert "api_key" not in spec.model_dump()


# --------------------------------------------------------------------------
# URL normalization
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "given,expected",
    [
        ("http://gpu:8000/v1", "http://gpu:8000/v1/chat/completions"),
        ("http://gpu:8000/v1/", "http://gpu:8000/v1/chat/completions"),
        ("http://gpu:8000/v1/chat/completions", "http://gpu:8000/v1/chat/completions"),
        ("https://host", "https://host/chat/completions"),
    ],
)
def test_build_chat_url(given: str, expected: str) -> None:
    """Base URLs normalize to the completions endpoint exactly once."""
    assert build_chat_url(given) == expected


# --------------------------------------------------------------------------
# adapter behaviour
# --------------------------------------------------------------------------


def test_adapter_satisfies_the_port_contract() -> None:
    """The remote adapter is a ReasoningPort."""
    adapter = OpenAICompatAdapter("m", "http://gpu:8000/v1")
    assert isinstance(adapter, ReasoningPort)


def test_complete_posts_and_returns_content() -> None:
    """A successful call returns the assistant message content."""
    seen: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> FakeResponse:
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.data.decode())
        return FakeResponse(_ok_body('{"ok": true}'))

    adapter = OpenAICompatAdapter(
        "qwen3.5-27b", "http://gpu:8000/v1", timeout_seconds=45.0, transport=transport
    )
    text = adapter.complete("Extract the event type.", temperature=0.1)

    assert text == '{"ok": true}'
    assert seen["url"] == "http://gpu:8000/v1/chat/completions"
    assert seen["timeout"] == 45.0
    assert seen["body"]["model"] == "qwen3.5-27b"
    assert seen["body"]["temperature"] == 0.1
    assert seen["body"]["messages"] == [{"role": "user", "content": "Extract the event type."}]
    assert seen["body"]["stream"] is False


def test_complete_json_parses_structured_output() -> None:
    """complete_json works against a remote server too."""
    adapter = OpenAICompatAdapter(
        "m",
        "http://gpu:8000/v1",
        transport=lambda r, t: FakeResponse(_ok_body('{"type": "DISCOVERY"}')),
    )
    assert adapter.complete_json("prompt") == {"type": "DISCOVERY"}


def test_system_prompt_is_sent_when_configured() -> None:
    """An optional system message is prepended."""
    captured: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> FakeResponse:
        captured["body"] = json.loads(request.data.decode())
        return FakeResponse(_ok_body())

    adapter = OpenAICompatAdapter(
        "m", "http://gpu:8000/v1", transport=transport, system_prompt="You extract events."
    )
    adapter.complete("hi")
    assert captured["body"]["messages"][0] == {"role": "system", "content": "You extract events."}


def test_api_key_becomes_bearer_header() -> None:
    """A configured key is sent as an Authorization header."""
    seen: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> FakeResponse:
        seen["headers"] = {k.lower(): v for k, v in dict(request.headers).items()}
        return FakeResponse(_ok_body())

    adapter = OpenAICompatAdapter("m", "http://gpu:8000/v1", api_key="tok", transport=transport)
    adapter.complete("hi")
    assert seen["headers"]["authorization"] == "Bearer tok"


def test_no_authorization_header_without_key() -> None:
    """Unauthenticated servers get no Authorization header."""
    seen: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> FakeResponse:
        seen["headers"] = {k.lower() for k in dict(request.headers)}
        return FakeResponse(_ok_body())

    adapter = OpenAICompatAdapter("m", "http://gpu:8000/v1", transport=transport)
    adapter.complete("hi")
    assert "authorization" not in seen["headers"]


def test_empty_prompt_is_rejected_without_a_request() -> None:
    """Blank prompts fail before any network call."""
    calls: list[int] = []

    def transport(request: Any, timeout: float) -> FakeResponse:
        calls.append(1)
        return FakeResponse(_ok_body())

    adapter = OpenAICompatAdapter("m", "http://gpu:8000/v1", transport=transport)
    with pytest.raises(ReasoningError, match="must not be empty"):
        adapter.complete("   ")
    assert calls == []


def test_missing_base_url_is_rejected() -> None:
    """Constructing without an endpoint is an error."""
    with pytest.raises(ReasoningError, match="base_url is required"):
        OpenAICompatAdapter("m", "")


def test_unreachable_host_is_classified_as_unavailable() -> None:
    """Connection failure maps to ReasoningUnavailableError."""
    from urllib.error import URLError

    def transport(request: Any, timeout: float) -> FakeResponse:
        raise URLError("connection refused")

    adapter = OpenAICompatAdapter("m", "http://gpu:8000/v1", transport=transport)
    with pytest.raises(ReasoningUnavailableError) as exc:
        adapter.complete("hi")
    assert "cannot reach" in str(exc.value)


def test_http_error_is_classified_without_leaking_the_token() -> None:
    """A 500 surfaces as ReasoningError and never echoes credentials."""
    from urllib.error import HTTPError

    def transport(request: Any, timeout: float) -> FakeResponse:
        raise HTTPError("http://gpu:8000/v1/chat/completions", 500, "boom", {}, None)

    adapter = OpenAICompatAdapter(
        "m", "http://gpu:8000/v1", api_key="super-secret", transport=transport
    )
    with pytest.raises(ReasoningError) as exc:
        adapter.complete("hi")
    assert "500" in str(exc.value)
    assert "super-secret" not in str(exc.value)


def test_timeout_is_classified() -> None:
    """A hung server maps to ReasoningUnavailableError."""

    def transport(request: Any, timeout: float) -> FakeResponse:
        raise TimeoutError

    adapter = OpenAICompatAdapter("m", "http://gpu:8000/v1", transport=transport)
    with pytest.raises(ReasoningUnavailableError, match="timed out"):
        adapter.complete("hi")


def test_invalid_json_body_is_rejected() -> None:
    """A non-JSON reply (e.g. an HTML error page) is surfaced clearly."""
    adapter = OpenAICompatAdapter(
        "m",
        "http://gpu:8000/v1",
        transport=lambda r, t: FakeResponse(b"<html>502 Bad Gateway</html>"),
    )
    with pytest.raises(ReasoningError, match="invalid JSON"):
        adapter.complete("hi")


def test_missing_choices_is_rejected() -> None:
    """A reply without choices is an error, not empty text."""
    adapter = OpenAICompatAdapter(
        "m",
        "http://gpu:8000/v1",
        transport=lambda r, t: FakeResponse(json.dumps({"error": "nope"}).encode()),
    )
    with pytest.raises(ReasoningError, match="no choices"):
        adapter.complete("hi")


def test_non_string_content_is_rejected() -> None:
    """Structured content that is not text is an error."""
    body = json.dumps({"choices": [{"message": {"content": {"a": 1}}}]}).encode()
    adapter = OpenAICompatAdapter(
        "m", "http://gpu:8000/v1", transport=lambda r, t: FakeResponse(body)
    )
    with pytest.raises(ReasoningError, match="no message.content"):
        adapter.complete("hi")


def test_unload_is_a_noop_and_available_reports_true() -> None:
    """The remote adapter holds no local resources."""
    adapter = OpenAICompatAdapter("m", "http://gpu:8000/v1")
    assert adapter.unload() is None
    assert adapter.available() is True


# --------------------------------------------------------------------------
# factory
# --------------------------------------------------------------------------


def test_factory_builds_remote_adapter(monkeypatch) -> None:
    """A remote spec yields the HTTP adapter, not the MLX one."""
    monkeypatch.setenv("TOK", "abc")
    spec = ModelSpec(
        model="qwen3.5-27b",
        backend="openai_compatible",
        base_url="http://gpu:8000/v1",
        api_key_env="TOK",
    )
    adapter = build_reasoning_adapter(spec)
    assert isinstance(adapter, OpenAICompatAdapter)
    assert adapter.base_url == "http://gpu:8000/v1"


def test_factory_builds_mlx_adapter_by_default() -> None:
    """No backend override keeps the MLX path."""
    adapter = build_reasoning_adapter(ModelSpec(model="Qwen3.5-27B"))
    assert type(adapter).__name__ == "QwenReasoningAdapter"


def test_factory_rejects_disabled_model() -> None:
    """A disabled spec cannot be built."""
    spec = ModelSpec(model="m", enabled=False)
    with pytest.raises(ValueError, match="disabled"):
        build_reasoning_adapter(spec)


def test_factory_from_loaded_settings(tmp_path) -> None:
    """End to end: a remote profile yields a working adapter."""
    d = _settings_dir(
        tmp_path,
        _profile(
            model="qwen3.5-27b",
            backend="openai_compatible",
            base_url="http://gpu-box.lan:8000/v1",
            timeout_seconds=90.0,
        ),
    )
    settings = load_settings(config_path=d / "default.yaml", models_path=d / "models.yaml")
    adapter = build_reasoning_adapter(settings.models.reasoning)
    assert isinstance(adapter, OpenAICompatAdapter)
    assert adapter.base_url == "http://gpu-box.lan:8000/v1"
    assert adapter.model == "qwen3.5-27b"


def test_extract_json_output_still_used_for_remote_text() -> None:
    """Prose-wrapped JSON from a remote server still parses."""
    text = 'Sure! Here you go:\n```json\n{"type": "DISCOVERY"}\n```'
    assert extract_json_output(text) == {"type": "DISCOVERY"}
