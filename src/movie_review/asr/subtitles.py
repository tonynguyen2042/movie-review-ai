"""Transcript subtitle sidecars: segments → SRT/VTT (transcript stage).

Pure helpers that render ``transcript.json`` segments as SubRip (``.srt``)
and WebVTT (``.vtt``) sidecars next to the JSON artifact. They exist so a
downstream vision model (Qwen3-VL) — or a human debugging a job — can read
dialogue with timestamps without parsing JSON.

Empty/whitespace-only segments are skipped: a blank cue carries no dialogue
and only adds noise to a prompt. Cue numbering is positional (1-based) over
the non-empty segments, in timestamp order, so output is deterministic for
identical input.
"""

from __future__ import annotations

from pathlib import Path

from movie_review.domain.transcript import TranscriptSegment

SRT_FILENAME = "transcript.srt"
VTT_FILENAME = "transcript.vtt"


def _srt_timestamp(seconds: float) -> str:
    """``HH:MM:SS,mmm`` (SubRip uses a comma)."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _vtt_timestamp(seconds: float) -> str:
    """``HH:MM:SS.mmm`` (WebVTT uses a dot)."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _cueable(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Non-empty segments in timestamp order."""
    kept = [seg for seg in segments if seg.text.strip()]
    return sorted(kept, key=lambda seg: (seg.start, seg.end))


def format_srt(segments: list[TranscriptSegment]) -> str:
    """Render segments in SubRip format."""
    blocks = [
        f"{index}\n{_srt_timestamp(seg.start)} --> {_srt_timestamp(seg.end)}\n{seg.text.strip()}"
        for index, seg in enumerate(_cueable(segments), start=1)
    ]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def format_vtt(segments: list[TranscriptSegment]) -> str:
    """Render segments in WebVTT format."""
    blocks = [
        f"{_vtt_timestamp(seg.start)} --> {_vtt_timestamp(seg.end)}\n{seg.text.strip()}"
        for seg in _cueable(segments)
    ]
    body = "\n\n".join(blocks)
    if not body:
        return "WEBVTT\n"
    return f"WEBVTT\n\n{body}\n"


def write_sidecars(directory: str | Path, segments: list[TranscriptSegment]) -> tuple[Path, Path]:
    """Write ``transcript.srt`` + ``transcript.vtt`` into ``directory``.

    Always overwrites (idempotent): the same segments produce byte-identical
    files, so a cache-hit rerun simply rewrites what is already there.
    """
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    srt_path = target_dir / SRT_FILENAME
    vtt_path = target_dir / VTT_FILENAME
    srt_path.write_text(format_srt(segments), encoding="utf-8")
    vtt_path.write_text(format_vtt(segments), encoding="utf-8")
    return srt_path, vtt_path
