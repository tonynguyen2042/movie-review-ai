"""Transcript normalization (T019).

Pure, timestamp-preserving cleanup for ASR output: Unicode normalization,
whitespace collapse, optional empty-segment removal. Segment IDs and
timestamps are never altered or renumbered (evidence references stay stable);
merging is deliberately out of scope.
"""

from __future__ import annotations

import re
import unicodedata

from movie_review.domain.transcript import TranscriptSegment

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """NFKC-normalize, collapse whitespace, drop control characters, strip."""
    normalized = unicodedata.normalize("NFKC", text)
    spaced = _WHITESPACE_RE.sub(" ", normalized)
    cleaned = "".join(char for char in spaced if char.isprintable() or char == " ")
    return cleaned.strip()


def normalize_segments(
    segments: list[TranscriptSegment], *, drop_empty: bool = True
) -> list[TranscriptSegment]:
    """Clean segment texts in place-order; optionally drop empties.

    Returns new segments sorted by start with original IDs and timestamps.
    """
    cleaned = [
        segment.model_copy(update={"text": normalize_text(segment.text)}) for segment in segments
    ]
    if drop_empty:
        cleaned = [segment for segment in cleaned if segment.text]
    return sorted(cleaned, key=lambda segment: (segment.start, segment.end))
