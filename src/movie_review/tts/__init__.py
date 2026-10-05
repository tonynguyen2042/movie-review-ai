"""Text-to-speech ports, adapters, chunking, and concat (T051-T054)."""

from movie_review.tts.chunks import (
    ChunkResult,
    TTSChunk,
    chunk_filename,
    plan_chunks,
    split_sentences,
    synthesize_chunk,
    synthesize_chunks,
    write_wav,
)
from movie_review.tts.concat import (
    METADATA_FILENAME,
    NARRATION_FILENAME,
    ConcatError,
    ConcatResult,
    concatenate,
)
from movie_review.tts.port import TTSError, TTSPort, TTSUnavailableError
from movie_review.tts.qwen_tts import QwenTTSAdapter

__all__ = [
    "ChunkResult",
    "ConcatError",
    "ConcatResult",
    "METADATA_FILENAME",
    "NARRATION_FILENAME",
    "QwenTTSAdapter",
    "TTSChunk",
    "TTSError",
    "TTSPort",
    "TTSUnavailableError",
    "chunk_filename",
    "concatenate",
    "plan_chunks",
    "split_sentences",
    "synthesize_chunk",
    "synthesize_chunks",
    "write_wav",
]
