"""Text-to-speech ports, adapters, and chunking (T051-T053)."""

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
from movie_review.tts.port import TTSError, TTSPort, TTSUnavailableError
from movie_review.tts.qwen_tts import QwenTTSAdapter

__all__ = [
    "ChunkResult",
    "QwenTTSAdapter",
    "TTSChunk",
    "TTSError",
    "TTSPort",
    "TTSUnavailableError",
    "chunk_filename",
    "plan_chunks",
    "split_sentences",
    "synthesize_chunk",
    "synthesize_chunks",
    "write_wav",
]
