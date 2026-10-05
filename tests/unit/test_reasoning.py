"""T033 acceptance (part 1): reasoning port and adapter without MLX."""

import importlib.util

import pytest

from movie_review.reasoning.port import (
    ReasoningError,
    ReasoningPort,
    ReasoningUnavailableError,
    extract_json_output,
)
from movie_review.reasoning.qwen import QwenReasoningAdapter

_HAS_MLX = importlib.util.find_spec("mlx_lm") is not None


def test_extract_json_object() -> None:
    assert extract_json_output('{"a": 1}') == {"a": 1}
    assert extract_json_output('prefix {"a": 1} suffix') == {"a": 1}
    assert extract_json_output('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_array() -> None:
    assert extract_json_output('[{"a": 1}]') == [{"a": 1}]
    assert extract_json_output('notes\n[{"a": 1}]\ndone') == [{"a": 1}]


def test_extract_json_rejects() -> None:
    with pytest.raises(ReasoningError):
        extract_json_output("no json here")


class _FakeBackend:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = outputs
        self.seen: list[tuple[str, float]] = []

    def __call__(self, prompt: str, temperature: float) -> str:
        self.seen.append((prompt, temperature))
        return self._outputs.pop(0)


def test_adapter_delegates() -> None:
    backend = _FakeBackend(['{"ok": true}'])
    adapter = QwenReasoningAdapter("custom-reasoning", backend=backend)
    assert adapter.model == "custom-reasoning"
    assert isinstance(adapter, ReasoningPort)
    assert adapter.complete_json("prompt?", temperature=0.1) == {"ok": True}
    assert backend.seen == [("prompt?", 0.1)]
    adapter.unload()


def test_adapter_rejects_empty_prompt() -> None:
    adapter = QwenReasoningAdapter("m", backend=_FakeBackend(["{}"]))
    with pytest.raises(ReasoningError, match="must not be empty"):
        adapter.complete("   ")


def test_adapter_without_runtime_unavailable() -> None:
    if _HAS_MLX:
        pytest.skip("MLX runtime present on this host")
    adapter = QwenReasoningAdapter("Qwen3.5-27B")
    with pytest.raises(ReasoningUnavailableError, match="Qwen3.5-27B"):
        adapter.complete("hi")
