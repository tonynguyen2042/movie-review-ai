"""Qwen3-VL adapter implementing :class:`VLMPort` (T023, spec section 15).

The MLX vision runtime is imported lazily so module import and the test
suite never require Apple Silicon, model weights, or network access
(NFR-006). Tests and non-MLX hosts inject an ``analyzer`` callable instead.
Model identity comes from the caller (configured ``models.vision``).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from movie_review.domain.scene_analysis import SceneAnalysis
from movie_review.vision.port import AnalysisInput, VLMError, VLMPort, VLMUnavailableError

RawAnalysis = Mapping[str, Any]
RawAnalyzer = Callable[[AnalysisInput, str], RawAnalysis | str]


def parse_analysis(payload: RawAnalysis | str, scene_id: str) -> SceneAnalysis:
    """Parse backend output (mapping or JSON text) into a validated analysis.

    The request's ``scene_id`` always wins: the model must not rename scenes.
    """
    if isinstance(payload, str):
        data = _extract_json(payload)
    elif isinstance(payload, Mapping):
        data = dict(payload)
    else:
        raise VLMError(f"Unsupported VLM payload type: {type(payload).__name__}")
    if not isinstance(data, dict):
        raise VLMError("VLM payload is not a JSON object")
    data["scene_id"] = scene_id
    try:
        return SceneAnalysis.model_validate(data)
    except ValueError as exc:
        raise VLMError(f"Invalid scene analysis: {exc}") from exc


def _extract_json(text: str) -> Any:
    """Parse JSON, tolerating prose or code fences around the object."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise VLMError("VLM output contains no JSON object")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise VLMError(f"VLM output is not valid JSON: {exc}") from exc


def _load_mlx_analyzer(model: str) -> RawAnalyzer:
    """Build the real MLX analyzer or raise :class:`VLMUnavailableError`."""
    try:
        import mlx_vlm  # type: ignore[import-not-found]
    except ImportError as exc:
        raise VLMUnavailableError(model, "mlx-vlm is not installed") from exc

    def _analyze(analysis_input: AnalysisInput, prompt: str) -> RawAnalysis | str:
        try:
            raw = mlx_vlm.analyze(
                [str(frame) for frame in analysis_input.frames],
                prompt,
                model=model,
            )
        except Exception as exc:
            raise VLMError(f"Qwen3-VL analysis failed: {exc}") from exc
        return cast("RawAnalysis | str", raw)

    return _analyze


class QwenVLAdapter(VLMPort):
    """Qwen3-VL family via MLX (model name supplied by caller)."""

    def __init__(self, model: str, analyzer: RawAnalyzer | None = None) -> None:
        self._model = model
        self._analyzer = analyzer

    @property
    def model(self) -> str:
        """Configured model identity."""
        return self._model

    def _ensure_loaded(self) -> RawAnalyzer:
        if self._analyzer is None:
            self._analyzer = _load_mlx_analyzer(self._model)
        return self._analyzer

    def analyze(self, analysis_input: AnalysisInput, prompt: str) -> SceneAnalysis:
        if not analysis_input.frames:
            raise VLMError("Analysis requires at least one frame")
        for frame in analysis_input.frames:
            if not Path(frame).is_file():
                raise VLMError(f"Frame file not found: {frame}")
        raw = self._ensure_loaded()(analysis_input, prompt)
        return parse_analysis(raw, analysis_input.scene_id)

    def unload(self) -> None:
        """Drop the backend so its memory can be reclaimed (plan section 6)."""
        self._analyzer = None
        try:
            import mlx.core as mx  # type: ignore[import-not-found]

            mx.clear_cache()
        except ImportError:
            pass
