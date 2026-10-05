"""Text-to-speech ports, adapters, chunking, concat, reconcile (T051-T055)."""

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
from movie_review.tts.reconcile import (
    ReconcileResult,
    ReconciliationError,
    measure_wav,
    reconcile_script,
    run_reconciliation,
)

__all__ = [
    "ChunkResult",
    "ConcatError",
    "ConcatResult",
    "METADATA_FILENAME",
    "NARRATION_FILENAME",
    "QwenTTSAdapter",
    "ReconcileResult",
    "ReconciliationError",
    "TTSChunk",
    "TTSError",
    "TTSPort",
    "TTSUnavailableError",
    "chunk_filename",
    "concatenate",
    "measure_wav",
    "plan_chunks",
    "reconcile_script",
    "run_reconciliation",
    "split_sentences",
    "synthesize_chunk",
    "synthesize_chunks",
    "write_wav",
]
