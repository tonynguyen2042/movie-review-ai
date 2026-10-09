"""Script translation: review script → target language (T107).

The review is written in the movie's own language. When the narration has to be
spoken in another one, the translation happens here, as its own stage, before any
audio exists: chunking, synthesis, subtitles and the quality gate then all work
on one language and cannot disagree with each other.

A translated script goes to its own file and the source is left alone. Overwriting
review-script.json would make the source unrecoverable, so changing the target
language later would translate the previous translation.

When the target equals the source -- which is what an omitted target means --
nothing is translated and nothing is written. That is the common case and it has
to cost nothing.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from movie_review.artifacts import manager as artifacts
from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.cache.manager import CacheManager
from movie_review.config.prompts import Prompt, load_prompt, render
from movie_review.config.settings import ModelSpec
from movie_review.domain import Artifact, JobStatus, ReviewScript, ReviewSection
from movie_review.jobs.state_machine import JobNotFoundError
from movie_review.pipeline.context import StageContext
from movie_review.pipeline.progress import ProgressReporter, WorkProgress
from movie_review.reasoning.factory import build_reasoning_adapter
from movie_review.reasoning.port import ReasoningPort
from movie_review.review.writer import SCRIPT_FILENAME
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "review-translate"
STAGE_VERSION = "v1"
#: Translation output is addressed under the review stage rather than a directory
#: of its own, so everything about the script stays in one place.
STAGE_DIRNAME = "review"

#: A language tag safe to embed in a filename. The tag names the output file, so
#: an unchecked value would let a caller escape the job directory.
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:[-_][a-z0-9]{2,8})?$")

#: Status marker the review writer emits for claims it cannot support.
MARKER = "INSUFFICIENT_EVIDENCE"

#: Lower than the writer's temperature: a translation should not be creative.
TRANSLATION_TEMPERATURE = 0.2


class TranslationError(Exception):
    """Translation failed in a classified way."""


@dataclass
class TranslationResult:
    """Outcome of one translation run."""

    script: ReviewScript
    script_path: Path | None
    translated_paragraphs: int
    cache_hits: int
    skipped: bool


# ---------------------------------------------------------------------------
# Language tags
# ---------------------------------------------------------------------------


def validate_language(language: str) -> str:
    """Normalise a language tag, rejecting anything unusable as a filename.

    Args:
        language: a tag such as ``en``, ``vi`` or ``pt-BR``.

    Returns:
        The trimmed, lower-cased tag.

    Raises:
        TranslationError: if the tag is empty or not a plain language tag.
    """
    normalized = language.strip().lower()
    if not _LANGUAGE_RE.fullmatch(normalized):
        raise TranslationError(
            f"Unsupported language tag {language!r}; expected something like 'en', 'vi' or 'pt-BR'"
        )
    return normalized


def needs_translation(source_language: str, target_language: str) -> bool:
    """Whether the two tags differ, so translation must run at all."""
    return validate_language(source_language) != validate_language(target_language)


# ---------------------------------------------------------------------------
# Artifact paths
# ---------------------------------------------------------------------------


def source_script_path(jobs_dir: str | Path, job_id: str) -> Path:
    """The source-language script, as written by the review stage."""
    return artifacts.artifact_path(jobs_dir, job_id, STAGE_DIRNAME, SCRIPT_FILENAME)


def translated_script_path(jobs_dir: str | Path, job_id: str, target_language: str) -> Path:
    """Where a translation for ``target_language`` is kept."""
    tag = validate_language(target_language)
    return artifacts.artifact_path(jobs_dir, job_id, STAGE_DIRNAME, f"review-script.{tag}.json")


def effective_script_path(jobs_dir: str | Path, job_id: str, target_language: str) -> Path:
    """The script every downstream stage should read.

    The translation when one exists, the source otherwise. Callers use this
    instead of :func:`source_script_path` so a job that asked for another
    language cannot be spoken in the source one -- and a job that did not ask is
    untouched.
    """
    translated = translated_script_path(jobs_dir, job_id, target_language)
    return translated if translated.is_file() else source_script_path(jobs_dir, job_id)


def load_script(path: Path) -> ReviewScript:
    """Read a script document written by the review or translation stage."""
    import json

    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    return ReviewScript.model_validate(document["script"])


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


def _cache_spec(
    text: str, source: str, target: str, model_id: str, prompt_version: str
) -> CacheSpec:
    return CacheSpec(
        stage=STAGE_NAME,
        stage_version=STAGE_VERSION,
        input_hash=artifacts.sha256_bytes(text.encode("utf-8")),
        model_id=model_id,
        generation_config={
            "source_language": source,
            "target_language": target,
            "prompt_version": prompt_version,
        },
    )


def _check_markers(source: str, translated: str) -> None:
    """Evidence markers must survive translation.

    ``INSUFFICIENT_EVIDENCE`` is a status code, not a word. A model that
    translates it, rewords it or drops it turns "we cannot support this" into a
    confident sentence -- the one failure mode this pipeline exists to prevent --
    so a lost marker fails the paragraph rather than passing through.
    """
    expected = source.count(MARKER)
    if expected and translated.count(MARKER) < expected:
        raise TranslationError(
            f"Translation lost an {MARKER} marker; refusing to publish narration "
            "that hides missing evidence"
        )


def _translate_text(
    reasoner: ReasoningPort,
    *,
    prompt: Prompt,
    prompt_version: str,
    source: str,
    target: str,
    text: str,
) -> str:
    """One paragraph through the model, with the reply validated."""
    rendered = render(prompt, source_language=source, target_language=target, text=text)
    try:
        raw = reasoner.complete_json(rendered, temperature=TRANSLATION_TEMPERATURE)
    except Exception as exc:
        raise TranslationError(f"Translation call failed: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
        raise TranslationError(
            f"Translation of a paragraph returned no text field ({prompt_version})"
        )
    result: str = str(raw["text"]).strip()
    if not result:
        raise TranslationError("Translation returned empty text")
    _check_markers(text, result)
    return result


def _translate_section(
    section: ReviewSection,
    *,
    cache: CacheManager,
    source: str,
    target: str,
    prompt: Prompt,
    prompt_version: str,
    reasoner: ReasoningPort,
    model_id: str,
) -> tuple[ReviewSection, int, int]:
    """Translate one section; returns it plus (translated, cache_hits) counts."""
    paragraphs: list[Any] = []
    translated = 0
    hits = 0
    for paragraph in section.paragraphs:
        key = cache_key(_cache_spec(paragraph.text, source, target, model_id, prompt_version))
        cached = cache.lookup_json(key)
        if isinstance(cached, dict) and isinstance(cached.get("text"), str):
            text = cached["text"]
            hits += 1
        else:
            text = _translate_text(
                reasoner,
                prompt=prompt,
                prompt_version=prompt_version,
                source=source,
                target=target,
                text=paragraph.text,
            )
            cache.store_json(key, {"text": text})
            translated += 1
        _check_markers(paragraph.text, text)
        paragraphs.append(paragraph.model_copy(update={"text": text}))
    return section.model_copy(update={"paragraphs": paragraphs}), translated, hits


def translate_script(
    script: ReviewScript,
    ctx: StageContext,
    *,
    source_language: str,
    target_language: str,
    spec: ModelSpec,
    reasoner: ReasoningPort | None = None,
    prompt_version: str | None = None,
    on_progress: ProgressReporter | None = None,
) -> TranslationResult:
    """Translate ``script`` paragraph by paragraph and persist the result.

    ``spec`` is the dedicated translation model, not the reasoning one: a
    translation model is typically a different size, sometimes on a different
    host, and it is the one the operator would want to swap without touching
    anything else. The adapter is built from the spec, so ``backend:
    openai_compatible`` is honoured rather than assumed to be local MLX.

    Each paragraph is cached on its own text, its target language, the model and
    the prompt version, so a retry after a failure re-translates only what is
    missing, editing one paragraph does not invalidate the rest, and pointing at
    a different translation model produces different output rather than reusing
    the previous model's.
    """
    source = validate_language(source_language)
    target = validate_language(target_language)
    if not needs_translation(source, target):
        return TranslationResult(
            script=script,
            script_path=None,
            translated_paragraphs=0,
            cache_hits=0,
            skipped=True,
        )

    started = time.perf_counter()
    try:
        job = ctx.manager.get(ctx.job_id)
    except JobNotFoundError as exc:
        raise TranslationError(f"Unknown job: {ctx.job_id}") from exc
    if job.status is JobStatus.FAILED:
        raise TranslationError(f"Job {ctx.job_id} failed; use retry to continue")

    prompt = load_prompt("translate", prompt_version)
    version = f"{prompt.name}:{prompt.version}"
    # Built from the spec so a remote translation endpoint is actually used;
    # constructing QwenReasoningAdapter directly would demand MLX on every host,
    # the same defect the other stages had.
    active = reasoner or build_reasoning_adapter(spec)
    model_id = active.model
    sections: list[ReviewSection] = []
    translated = 0
    hits = 0
    total = len(script.sections)
    try:
        for index, section in enumerate(script.sections, start=1):
            done, made, found = _translate_section(
                section,
                cache=ctx.cache,
                source=source,
                target=target,
                prompt=prompt,
                prompt_version=version,
                reasoner=active,
                model_id=model_id,
            )
            translated += made
            hits += found
            sections.append(done)
            if on_progress is not None:
                on_progress(WorkProgress(done=index, total=total, label=f"section {index}/{total}"))
    finally:
        active.unload()

    translated_script = ReviewScript(sections=sections)
    document = {
        "job_id": ctx.job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "prompt": version,
        "model": model_id,
        "source_language": source,
        "target_language": target,
        "script": translated_script.model_dump(mode="json"),
    }
    path = translated_script_path(ctx.jobs_dir, ctx.job_id, target)
    output_hash = artifacts.write_json(path, document)
    repo.save_artifact(
        ctx.conn,
        Artifact(
            artifact_id=f"{ctx.job_id}-review-script-{target}",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(ctx.jobs_dir, ctx.job_id, path),
            input_hash=artifacts.sha256_bytes(script.model_dump_json().encode("utf-8")),
            output_hash=output_hash,
            model=model_id,
            prompt_version=version,
        ),
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    with ulog.logging_context(job_id=ctx.job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="stage.completed",
            status="ok",
            duration_ms=duration_ms,
            source_language=source,
            target_language=target,
            translated_paragraphs=translated,
            cache_hits=hits,
            skipped=False,
        )
    return TranslationResult(
        script=translated_script,
        script_path=path,
        translated_paragraphs=translated,
        cache_hits=hits,
        skipped=False,
    )
