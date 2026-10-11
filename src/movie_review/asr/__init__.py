"""Speech recognition ports and adapters (T016 port, T017 adapter, T018 stage)."""

from movie_review.asr.factory import build_asr_adapter
from movie_review.asr.normalize import normalize_segments, normalize_text
from movie_review.asr.openai_compat import OpenAICompatASRAdapter
from movie_review.asr.port import ASRError, ASRPort, ModelUnavailableError
from movie_review.asr.subtitles import format_srt, format_vtt, write_sidecars
from movie_review.asr.transcript import TranscriptError, TranscriptResult, run_transcript
from movie_review.asr.whisper_mlx import WhisperMLXAdapter, map_segments

__all__ = [
    "ASRError",
    "ASRPort",
    "ModelUnavailableError",
    "OpenAICompatASRAdapter",
    "TranscriptError",
    "TranscriptResult",
    "WhisperMLXAdapter",
    "build_asr_adapter",
    "format_srt",
    "format_vtt",
    "map_segments",
    "normalize_segments",
    "normalize_text",
    "run_transcript",
    "write_sidecars",
]
