"""Whisper MLX adapter implementing :class:`ASRPort` (T017, spec section 13).

Default model family is configured (``models.asr``), never hard-coded here.
The MLX runtime is imported lazily so module import and the test suite never
require Apple Silicon, model weights, or network access (NFR-006). Tests and
non-MLX hosts inject a ``transcriber`` callable instead.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from movie_review.asr.port import ASRError, ASRPort, ModelUnavailableError
from movie_review.domain.transcript import TranscriptSegment

RawSegment = Mapping[str, Any]
RawTranscriber = Callable[[str, str | None], Iterable[RawSegment]]

DEFAULT_LANGUAGE = "en"


def _confidence(raw: RawSegment) -> float:
    """Best-effort confidence in [0, 1] from backend score fields."""
    if "confidence" in raw:
        return max(0.0, min(1.0, float(raw["confidence"])))
    if "avg_logprob" in raw:
        return max(0.0, min(1.0, math.exp(float(raw["avg_logprob"]))))
    return 1.0


def map_segments(
    raw_segments: Iterable[RawSegment], language: str | None
) -> list[TranscriptSegment]:
    """Map backend-agnostic raw segments to validated :class:`TranscriptSegment`."""
    mapped = []
    for index, raw in enumerate(raw_segments):
        try:
            start = float(raw["start"])
            end = float(raw["end"])
            text = str(raw.get("text", ""))
        except (KeyError, TypeError, ValueError) as exc:
            raise ASRError(f"Uninterpretable ASR segment #{index}: {exc}") from exc
        try:
            mapped.append(
                TranscriptSegment(
                    segment_id=f"seg_{index:05d}",
                    start=start,
                    end=end,
                    text=text,
                    language=language,
                    confidence=_confidence(raw),
                )
            )
        except ValueError as exc:
            raise ASRError(f"Invalid ASR segment #{index}: {exc}") from exc
    return mapped


def _transcribe_with(mlx_whisper: Any, model: str, audio_path: str, language: str | None) -> Any:
    """Call Whisper, passing the language through when there is one.

    Without the language, Whisper auto-detects. A job told to transcribe
    Japanese could then come back in a mis-detected language while the
    transcript rows and the cache key both recorded the language that was
    asked for -- so the pipeline believed something the audio did not say.
    """
    if language:
        return mlx_whisper.transcribe(audio_path, path_or_hf_repo=model, language=language)
    return mlx_whisper.transcribe(audio_path, path_or_hf_repo=model)


def _load_mlx_transcriber(model: str) -> RawTranscriber:
    """Build the real MLX transcriber or raise :class:`ModelUnavailableError`."""
    try:
        import mlx_whisper  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ModelUnavailableError(model, "mlx-whisper is not installed") from exc

    def _transcribe(audio_path: str, language: str | None) -> Iterable[RawSegment]:
        try:
            result = _transcribe_with(mlx_whisper, model, audio_path, language)
        except Exception as exc:
            raise ASRError(f"Whisper transcription failed for {audio_path}: {exc}") from exc
        segments = result.get("segments", []) if isinstance(result, dict) else []
        return [dict(segment) for segment in segments]

    return _transcribe


class WhisperMLXAdapter(ASRPort):
    """Whisper large-v3-turbo family via MLX (model name supplied by caller)."""

    def __init__(self, model: str, transcriber: RawTranscriber | None = None) -> None:
        self._model = model
        self._transcriber = transcriber
        self._loaded = transcriber is not None

    @property
    def model(self) -> str:
        """Configured model identity."""
        return self._model

    def _ensure_loaded(self) -> RawTranscriber:
        if self._transcriber is None:
            self._transcriber = _load_mlx_transcriber(self._model)
            self._loaded = True
        return self._transcriber

    def transcribe(
        self, audio_path: str | Path, *, language: str | None = None
    ) -> list[TranscriptSegment]:
        src = Path(audio_path)
        if not src.is_file():
            raise ASRError(f"Audio file not found: {src}")
        active_language = language or DEFAULT_LANGUAGE
        raw = self._ensure_loaded()(str(src), active_language)
        return map_segments(raw, active_language)

    def unload(self) -> None:
        """Drop the backend so its memory can be reclaimed (plan section 6)."""
        self._transcriber = None
        self._loaded = False
        try:
            import mlx.core as mx  # type: ignore[import-not-found]

            mx.clear_cache()
        except ImportError:
            pass
