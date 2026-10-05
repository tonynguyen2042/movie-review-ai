"""Publishing metadata generation (T096, spec Phase 12).

Derives video title, description, tags, and chapter markers from an
assembled review script. Pure domain logic: no model, network, or file I/O.
Publication targets enforce their own field limits; this module normalizes
to those limits and never invents plot facts beyond the script text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from movie_review.domain import ReviewScript

# YouTube field limits (max lengths, in characters).
TITLE_MAX_CHARS = 100
DESCRIPTION_MAX_CHARS = 5000
MAX_TAGS = 500

# Words that carry no topical signal when harvested for tags.
_TAG_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "do",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "our",
        "she",
        "so",
        "than",
        "that",
        "the",
        "their",
        "then",
        "there",
        "they",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    }
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_POSSESSIVE_RE = re.compile(r"'s?$")


class MetadataError(ValueError):
    """Metadata generation failed in a classified way."""


@dataclass(frozen=True)
class Chapter:
    """One chapter marker derived from a script section."""

    index: int
    title: str
    start_seconds: float


@dataclass(frozen=True)
class VideoMetadata:
    """Publishing metadata for one rendered review video."""

    title: str
    description: str
    tags: list[str] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)


def _collapse(text: str) -> str:
    """Collapse all whitespace (including newlines) into single spaces."""
    return " ".join(text.split())


def _truncate(value: str, limit: int) -> str:
    """Trim to ``limit`` characters, breaking on a word boundary when possible."""
    cleaned = _collapse(value)
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[:limit]
    boundary = clipped.rfind(" ")
    if boundary > 0:
        clipped = clipped[:boundary]
    return clipped.rstrip()


def _truncate_lines(value: str, limit: int) -> str:
    """Trim while preserving line structure (newlines kept intact)."""
    if len(value) <= limit:
        return value
    clipped = value[:limit]
    boundary = clipped.rfind("\n")
    if boundary > 0:
        clipped = clipped[:boundary]
    return clipped.rstrip()


def script_text(script: ReviewScript) -> str:
    """Concatenate all paragraph text in section/paragraph order."""
    parts = [paragraph.text for section in script.sections for paragraph in section.paragraphs]
    return "\n".join(parts)


def build_title(script: ReviewScript, movie_title: str = "") -> str:
    """Build a video title from the movie title and the script's opening line."""
    base = _truncate(movie_title.strip(), TITLE_MAX_CHARS)
    hook = ""
    for section in script.sections:
        for paragraph in section.paragraphs:
            first_sentence = paragraph.text.strip().split(". ")[0].strip()
            if first_sentence:
                hook = first_sentence
                break
        if hook:
            break
    if base and hook:
        return _truncate(f"{base} Review | {hook}", TITLE_MAX_CHARS)
    return _truncate(base or hook or "Movie Review", TITLE_MAX_CHARS)


def build_description(
    script: ReviewScript,
    movie_title: str = "",
    chapters: list[Chapter] | None = None,
) -> str:
    """Build a description: summary paragraph followed by a chapter list."""
    body = script_text(script)
    summary = _truncate_lines(body, DESCRIPTION_MAX_CHARS - 500)
    lines: list[str] = []
    if movie_title:
        lines.append(f"{movie_title} review.")
    lines.append(summary)
    lines.append("")
    lines.append("Chapters:")
    for chapter in chapters or []:
        lines.append(f"- {_format_clock(chapter.start_seconds)} {chapter.title}")
    return _truncate_lines("\n".join(lines), DESCRIPTION_MAX_CHARS)


def build_tags(script: ReviewScript, extra: list[str] | None = None) -> list[str]:
    """Derive topical tags from the script text plus explicit extras."""
    counts: dict[str, int] = {}
    for word in _WORD_RE.findall(script_text(script)):
        token = _POSSESSIVE_RE.sub("", word.lower()).rstrip("'")
        if len(token) < 3 or token in _TAG_STOPWORDS:
            continue
        counts[token] = counts.get(token, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    tags: list[str] = []
    for token, _count in ranked:
        if token not in tags:
            tags.append(token)
        if len(tags) >= MAX_TAGS:
            break

    for tag in extra or []:
        normalized = _truncate(tag, TITLE_MAX_CHARS)
        if normalized and normalized not in tags:
            tags.append(normalized)
        if len(tags) >= MAX_TAGS:
            break
    return tags


def build_chapters(script: ReviewScript, start_seconds: float = 0.0) -> list[Chapter]:
    """Build one chapter per section, spaced by its paragraphs' target seconds."""
    chapters: list[Chapter] = []
    cursor = start_seconds
    for index, section in enumerate(script.sections):
        title = _truncate(section.type.replace("_", " ").strip().title(), TITLE_MAX_CHARS)
        chapters.append(Chapter(index=index + 1, title=title, start_seconds=round(cursor, 3)))
        cursor += sum(float(paragraph.target_seconds) for paragraph in section.paragraphs)
    return chapters


def _format_clock(seconds: float) -> str:
    """Format seconds as ``M:SS`` for chapter listing."""
    total = max(0, int(round(seconds)))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


def generate_metadata(
    script: ReviewScript,
    movie_title: str = "",
    extra_tags: list[str] | None = None,
) -> VideoMetadata:
    """Generate title, description, tags, and chapters for a review video."""
    if not script.sections:
        raise MetadataError("Cannot generate metadata for an empty script")

    chapters = build_chapters(script)
    return VideoMetadata(
        title=build_title(script, movie_title),
        description=build_description(script, movie_title, chapters),
        tags=build_tags(script, extra_tags),
        chapters=chapters,
    )
