"""T023 acceptance: Qwen3-VL adapter parses output without requiring MLX."""

import importlib.util
from pathlib import Path

import pytest

from movie_review.vision.port import AnalysisInput, VLMError, VLMPort, VLMUnavailableError
from movie_review.vision.qwen_vl import QwenVLAdapter, parse_analysis
from tests.helpers import (
    _input,
)

_HAS_MLX = importlib.util.find_spec("mlx_vlm") is not None


def test_parse_dict_forces_scene_id() -> None:
    analysis = parse_analysis(
        {"scene_id": "scene_999", "location": "dock", "importance": 0.7}, "scene_000001"
    )
    assert analysis.scene_id == "scene_000001"
    assert analysis.location == "dock"


def test_parse_json_with_prose() -> None:
    payload = 'Here is the analysis:\n```json\n{"location": "dock"}\n```'
    assert parse_analysis(payload, "s").location == "dock"


def test_parse_rejects_bad_payloads() -> None:
    with pytest.raises(VLMError):
        parse_analysis("no json here", "s")
    with pytest.raises(VLMError):
        parse_analysis("[1, 2]", "s")
    with pytest.raises(VLMError):
        parse_analysis({"importance": 2.0}, "s")
    with pytest.raises(VLMError):
        parse_analysis(42, "s")  # type: ignore[arg-type]


def test_adapter_uses_injected_analyzer(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def _fake(analysis_input: AnalysisInput, prompt: str) -> dict[str, object]:
        seen["prompt"] = prompt
        seen["frames"] = len(analysis_input.frames)
        return {"location": "dock", "characters": ["John"]}

    adapter = QwenVLAdapter("custom-vision-model", analyzer=_fake)
    assert adapter.model == "custom-vision-model"
    assert isinstance(adapter, VLMPort)
    result = adapter.analyze(_input(tmp_path), prompt="describe")
    assert result.location == "dock"
    assert result.characters == ["John"]
    assert seen == {"prompt": "describe", "frames": 1}


def test_adapter_rejects_missing_frames(tmp_path: Path) -> None:
    adapter = QwenVLAdapter("m", analyzer=lambda i, p: {})
    with pytest.raises(VLMError, match="at least one frame"):
        adapter.analyze(AnalysisInput(scene_id="s", frames=[]), prompt="p")
    with pytest.raises(VLMError, match="not found"):
        adapter.analyze(AnalysisInput(scene_id="s", frames=[tmp_path / "absent.jpg"]), prompt="p")


def test_adapter_unload_releases_backend(tmp_path: Path) -> None:
    adapter = QwenVLAdapter("m", analyzer=lambda i, p: {"location": "x"})
    adapter.analyze(_input(tmp_path), prompt="p")
    adapter.unload()
    if _HAS_MLX:
        pytest.skip("MLX runtime present; unload path differs")
    with pytest.raises(VLMUnavailableError):
        adapter.analyze(_input(tmp_path), prompt="p")


def test_adapter_without_runtime_unavailable(tmp_path: Path) -> None:
    if _HAS_MLX:
        pytest.skip("MLX runtime present on this host")
    adapter = QwenVLAdapter("Qwen3-VL")
    with pytest.raises(VLMUnavailableError, match="Qwen3-VL"):
        adapter.analyze(_input(tmp_path), prompt="p")
