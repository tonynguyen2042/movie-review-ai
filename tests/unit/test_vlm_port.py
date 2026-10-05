"""T022 acceptance: visual analysis contract and VLM port behavior."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from movie_review.domain import SceneAnalysis
from movie_review.vision.port import AnalysisInput, VLMError, VLMPort, VLMUnavailableError


def _analysis() -> SceneAnalysis:
    return SceneAnalysis(
        scene_id="scene_000001",
        location="abandoned warehouse",
        characters=["John"],
        actions=["runs"],
        importance=0.82,
    )


def test_analysis_defaults() -> None:
    analysis = SceneAnalysis(scene_id="s")
    assert analysis.location == ""
    assert analysis.characters == []
    assert analysis.importance == pytest.approx(0.5)
    assert SceneAnalysis.model_validate(analysis.model_dump()) == analysis


def test_analysis_rejects_bad_importance() -> None:
    with pytest.raises(ValidationError):
        SceneAnalysis(scene_id="s", importance=1.5)


class _FakeVLM(VLMPort):
    def __init__(self, analysis: SceneAnalysis) -> None:
        self._analysis = analysis
        self.seen_prompt: str | None = None
        self.unloaded = False

    def analyze(self, analysis_input: AnalysisInput, prompt: str) -> SceneAnalysis:
        assert analysis_input.frames
        assert analysis_input.scene_id == "scene_000001"
        self.seen_prompt = prompt
        return self._analysis

    def unload(self) -> None:
        self.unloaded = True


def test_port_contract() -> None:
    fake = _FakeVLM(_analysis())
    result = fake.analyze(
        AnalysisInput(scene_id="scene_000001", frames=[Path("f.jpg")]),
        prompt="describe",
    )
    assert result.location == "abandoned warehouse"
    assert fake.seen_prompt == "describe"
    fake.unload()
    assert fake.unloaded is True


def test_port_requires_methods() -> None:
    with pytest.raises(TypeError):
        VLMPort()  # type: ignore[abstract]


def test_unavailable_error() -> None:
    error = VLMUnavailableError("Qwen3-VL", "no MLX on this host")
    assert isinstance(error, VLMError)
    assert "Qwen3-VL" in str(error)
