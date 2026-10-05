"""Speaker diarization ports and adapters (T020 port, T021 adapter)."""

from movie_review.diarization.initial import EnergyDiarizer, VadConfig, detect_speech_spans
from movie_review.diarization.port import (
    DiarizationError,
    DiarizationModelUnavailableError,
    DiarizationPort,
)

__all__ = [
    "DiarizationError",
    "DiarizationModelUnavailableError",
    "DiarizationPort",
    "EnergyDiarizer",
    "VadConfig",
    "detect_speech_spans",
]
