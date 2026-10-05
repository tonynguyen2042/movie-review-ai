"""Subtitle generation from narration timing (T059, spec section 47).

Cues derive from actual TTS segment timing (manifest starts plus measured
narration durations), never from word-count estimates alone. Words spread
evenly within their paragraph span; word-level forced alignment is out of
scope and documented as such.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from movie_review.domain import RenderManifest

MAX_CHARS_PER_CUE = 84


@dataclass(frozen=True)
class SubtitleCue:
    """One timed subtitle entry."""

    index: int
    start: float
    end: float
    text: str


def format_timestamp(seconds: float) -> str:
    """SRT timestamp ``HH:MM:SS,mmm`` (clamped at zero)."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_timestamp(value: str) -> float:
    """Parse ``HH:MM:SS,mmm`` back to seconds."""
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise SubtitleError(f"Invalid SRT timestamp: {value!r}")
    hours, minutes, secs, millis = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + secs + millis / 1000


class SubtitleError(ValueError):
    """Subtitle generation failed in a classified way."""


def split_text(text: str, limit: int = MAX_CHARS_PER_CUE) -> list[str]:
    """Greedy word-wrap into cue-sized chunks."""
    words = text.split()
    if not words:
        return []
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > limit and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def build_cues(manifest: RenderManifest, texts: dict[str, str]) -> list[SubtitleCue]:
    """Build cues from manifest timing; paragraphs evenly spread per span."""
    cues: list[SubtitleCue] = []
    for segment in manifest.segments:
        text = texts.get(segment.paragraph_id, "")
        chunks = split_text(text)
        if not chunks:
            continue
        span = segment.duration / len(chunks)
        for position, chunk in enumerate(chunks):
            start = segment.start + position * span
            cues.append(SubtitleCue(index=len(cues) + 1, start=start, end=start + span, text=chunk))
    return cues


def format_srt(cues: list[SubtitleCue]) -> str:
    """Render cues in SubRip format."""
    blocks = [
        f"{cue.index}\n{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}\n{cue.text}"
        for cue in cues
    ]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def parse_srt(text: str) -> list[SubtitleCue]:
    """Parse SubRip back into cues (round-trip validation)."""
    cues: list[SubtitleCue] = []
    for block in text.strip().split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            raise SubtitleError(f"Malformed SRT block: {block!r}")
        try:
            index = int(lines[0].strip())
        except ValueError as exc:
            raise SubtitleError(f"Bad SRT index: {lines[0]!r}") from exc
        arrow = lines[1].split("-->")
        if len(arrow) != 2:
            raise SubtitleError(f"Bad SRT timing line: {lines[1]!r}")
        cues.append(
            SubtitleCue(
                index=index,
                start=parse_timestamp(arrow[0]),
                end=parse_timestamp(arrow[1]),
                text="\n".join(lines[2:]),
            )
        )
    return cues


def write_srt(path: str | Path, cues: list[SubtitleCue]) -> Path:
    """Write cues to an SRT file; returns the path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(format_srt(cues), encoding="utf-8")
    return target
