"""A truncated VLM reply must not cost a whole pipeline run (T103).

A scene analysis run over a feature film reached scene 89 of ~100, then died:

    Cannot analyze scene_000089: VLM output contains no JSON object

Nothing was wrong with the reply's *shape*. The model opened the JSON object,
ran out of completion budget part-way through the lists, and the truncated text
had no closing brace -- so the parser reported a formatting failure for what is
actually a budget failure. Reproduced deliberately against a live server:

    max_tokens=12   finish_reason=length   has '{': True   has '}': False

Worse, the failure mode was indistinguishable from a refusal or a prose answer,
because the reply itself was never surfaced. Both are fixed here: truncation is
read from ``finish_reason``, one retry doubles the budget, and a reply that is
still unusable is quoted back in the error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from movie_review.config.settings import ModelSpec
from movie_review.vision.factory import build_vlm_adapter
from movie_review.vision.openai_compat import (
    DEFAULT_MAX_TOKENS,
    RETRY_INSTRUCTION,
    OpenAICompatVLMAdapter,
)
from movie_review.vision.port import AnalysisInput, VLMError, VLMUnavailableError
from tests.helpers import (
    _frame,
)

# A real reply, truncated the way max_tokens cuts one: no closing brace.
TRUNCATED = '{\n  "location": "Fury cargo hold",\n  "characters": ["a man"],\n  "actions": ['
GOOD = json.dumps(
    {
        "location": "Fury cargo hold",
        "characters": ["a man"],
        "actions": ["paces"],
        "objects": [],
        "emotions": [],
        "visual_events": [],
        "importance": 0.5,
        "confidence": 0.7,
    }
)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _chat(content: str, finish_reason: str = "stop") -> bytes:
    return json.dumps(
        {
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": content},
                }
            ]
        }
    ).encode()


def _input__vlm_truncation(tmp_path: Path) -> AnalysisInput:
    return AnalysisInput(
        scene_id="scene_000089", frames=[_frame(tmp_path)], dialogue="", previous_summary=None
    )


def _adapter(
    tmp_path: Path, replies: list[bytes], seen: list[dict[str, Any]], **kwargs: Any
) -> OpenAICompatVLMAdapter:
    def transport(request: Any, timeout: float) -> FakeResponse:
        payload = json.loads(request.data.decode())
        seen.append(payload)
        return FakeResponse(replies[min(len(seen) - 1, len(replies) - 1)])

    return OpenAICompatVLMAdapter("Qwen3-VL", "http://gpu:8000/v1", transport=transport, **kwargs)


# ---------------------------------------------------------------------------
# Truncation is recognised, and retried
# ---------------------------------------------------------------------------


def test_truncated_reply_is_retried_with_a_bigger_budget(tmp_path: Path) -> None:
    """The failure that killed the run: budget, not formatting."""
    seen: list[dict[str, Any]] = []
    adapter = _adapter(tmp_path, [_chat(TRUNCATED, "length"), _chat(GOOD)], seen, max_tokens=2048)

    analysis = adapter.analyze(_input__vlm_truncation(tmp_path), "prompt")

    assert analysis.location == "Fury cargo hold"
    assert len(seen) == 2
    assert seen[0]["max_tokens"] == 2048
    assert seen[1]["max_tokens"] == 4096, "the retry must actually change the budget"


def test_retry_asks_for_json_only(tmp_path: Path) -> None:
    """A second identical request would return the same unusable reply."""
    seen: list[dict[str, Any]] = []
    adapter = _adapter(tmp_path, [_chat(TRUNCATED, "length"), _chat(GOOD)], seen)

    adapter.analyze(_input__vlm_truncation(tmp_path), "ORIGINAL PROMPT")

    first_text = seen[0]["messages"][0]["content"][-1]["text"]
    second_text = seen[1]["messages"][0]["content"][-1]["text"]
    assert RETRY_INSTRUCTION not in first_text
    assert second_text.startswith("ORIGINAL PROMPT")
    assert RETRY_INSTRUCTION in second_text


def test_frames_are_not_resent_differently_on_retry(tmp_path: Path) -> None:
    """Same evidence both times; only the instruction and budget change."""
    seen: list[dict[str, Any]] = []
    adapter = _adapter(tmp_path, [_chat(TRUNCATED, "length"), _chat(GOOD)], seen)

    adapter.analyze(_input__vlm_truncation(tmp_path), "prompt")

    first_images = seen[0]["messages"][0]["content"][:-1]
    second_images = seen[1]["messages"][0]["content"][:-1]
    assert first_images == second_images


def test_complete_but_unparseable_reply_keeps_the_budget(tmp_path: Path) -> None:
    """No truncation means a bigger budget fixes nothing; the prompt is retried."""
    seen: list[dict[str, Any]] = []
    adapter = _adapter(
        tmp_path, [_chat("I cannot help with that."), _chat(GOOD)], seen, max_tokens=2048
    )

    adapter.analyze(_input__vlm_truncation(tmp_path), "prompt")

    assert seen[1]["max_tokens"] == 2048


def test_empty_reply_is_retried(tmp_path: Path) -> None:
    """A blank completion is a failure mode of its own, not a parse error."""
    seen: list[dict[str, Any]] = []
    adapter = _adapter(tmp_path, [_chat("", "stop"), _chat(GOOD)], seen)

    analysis = adapter.analyze(_input__vlm_truncation(tmp_path), "prompt")

    assert analysis.scene_id == "scene_000089"
    assert len(seen) == 2


# ---------------------------------------------------------------------------
# When the retry does not help, the error must explain itself
# ---------------------------------------------------------------------------


def test_persistent_truncation_reports_the_budget_and_the_reply(tmp_path: Path) -> None:
    """'contains no JSON object' alone sent the diagnosis nowhere."""
    seen: list[dict[str, Any]] = []
    adapter = _adapter(tmp_path, [_chat(TRUNCATED, "length")], seen, max_tokens=2048)

    with pytest.raises(VLMError) as excinfo:
        adapter.analyze(_input__vlm_truncation(tmp_path), "prompt")

    message = str(excinfo.value)
    assert "scene_000089" in message
    assert "length" in message
    # The budget named is the one in force on the final attempt, which is the
    # number the operator has to raise.
    assert "4096" in message, message
    assert "Fury cargo hold" in message, "the reply must be quoted back"
    assert len(seen) == 2


def test_refusal_is_reported_as_such_not_as_a_format_error(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []
    adapter = _adapter(tmp_path, [_chat("I cannot help with that.", "stop")], seen)

    with pytest.raises(VLMError) as excinfo:
        adapter.analyze(_input__vlm_truncation(tmp_path), "prompt")

    assert "cannot help with that" in str(excinfo.value)


def test_excerpt_is_bounded(tmp_path: Path) -> None:
    """A long refusal must not become a log line of thousands of characters."""
    seen: list[dict[str, Any]] = []
    adapter = _adapter(tmp_path, [_chat("no " * 5000, "stop")], seen)

    with pytest.raises(VLMError) as excinfo:
        adapter.analyze(_input__vlm_truncation(tmp_path), "prompt")

    assert len(str(excinfo.value)) < 600


# ---------------------------------------------------------------------------
# Failures that must not be retried
# ---------------------------------------------------------------------------


def test_transport_failure_is_not_retried(tmp_path: Path) -> None:
    """Repeating an unreachable server wastes time and hides the real problem."""
    from movie_review.remote import http as remote_http

    calls: list[int] = []

    def transport(request: Any, timeout: float) -> FakeResponse:
        calls.append(1)
        raise remote_http.RemoteUnavailableError("connection refused")

    adapter = OpenAICompatVLMAdapter("Qwen3-VL", "http://gpu:8000/v1", transport=transport)

    with pytest.raises(VLMUnavailableError):
        adapter.analyze(_input__vlm_truncation(tmp_path), "prompt")

    assert len(calls) == 1


def test_missing_frame_still_fails_immediately(tmp_path: Path) -> None:
    """Local validation, before any request is spent."""
    adapter = OpenAICompatVLMAdapter(
        "Qwen3-VL", "http://gpu:8000/v1", transport=lambda *_a, **_k: FakeResponse(b"{}")
    )
    with pytest.raises(VLMError, match="Frame file not found"):
        adapter.analyze(
            AnalysisInput(
                scene_id="scene_1",
                frames=[tmp_path / "absent.png"],
                dialogue="",
                previous_summary=None,
            ),
            "prompt",
        )


# ---------------------------------------------------------------------------
# max_tokens is configuration, not a constant in an adapter
# ---------------------------------------------------------------------------


def test_max_tokens_comes_from_the_profile() -> None:
    spec = ModelSpec(
        model="Qwen3-VL",
        backend="openai_compatible",
        base_url="http://gpu:8000/v1",
        max_tokens=8192,
    )
    adapter = build_vlm_adapter(spec)
    assert isinstance(adapter, OpenAICompatVLMAdapter)
    assert adapter._max_tokens == 8192


def test_max_tokens_falls_back_to_the_default() -> None:
    spec = ModelSpec(model="Qwen3-VL", backend="openai_compatible", base_url="http://gpu:8000/v1")
    adapter = build_vlm_adapter(spec)
    assert isinstance(adapter, OpenAICompatVLMAdapter)
    assert adapter._max_tokens == DEFAULT_MAX_TOKENS


def test_explicit_override_beats_the_profile() -> None:
    spec = ModelSpec(
        model="Qwen3-VL",
        backend="openai_compatible",
        base_url="http://gpu:8000/v1",
        max_tokens=8192,
    )
    adapter = build_vlm_adapter(spec, max_tokens=256)
    assert isinstance(adapter, OpenAICompatVLMAdapter)
    assert adapter._max_tokens == 256


def test_max_tokens_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        ModelSpec(
            model="Qwen3-VL",
            backend="openai_compatible",
            base_url="http://gpu:8000/v1",
            max_tokens=0,
        )
