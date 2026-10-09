"""Translate the review script before it is spoken (T107).

The request: add a target-language option, and when it is omitted use the
``language`` option's value as the target -- which means no translation at all.

Two findings shaped the implementation:

- ``--language`` was already accepted and then dropped. It reached the
  acceptance log and nothing else, so ASR auto-detected every time and the
  review had no language attached to it. Threading it through is part of this,
  not a separate fix.
- Four stages each opened ``review-script.json`` themselves. Left alone, a
  translated job would have been synthesized, reconciled and subtitled in the
  source language while the caller asked for another one.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import (
    ModelSpec,
    ModelsSettings,
    available_profiles,
    load_settings,
)
from movie_review.domain import Job, JobStatus, ReviewScript
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.pipeline.orchestrator import (
    STAGE_SEQUENCE,
    PipelineContext,
    _get_stage_function,
    load_effective_script,
)
from movie_review.reasoning.port import ReasoningPort
from movie_review.review.translate import (
    MARKER,
    TranslationError,
    TranslationResult,
    effective_script_path,
    load_script,
    needs_translation,
    source_script_path,
    translate_script,
    translated_script_path,
    validate_language,
)
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect

SOURCE = "vi"
TARGET = "en"


def _script(paragraphs: int = 2) -> ReviewScript:
    return ReviewScript.model_validate(
        {
            "sections": [
                {
                    "id": "sec_000",
                    "type": "intro",
                    "heading": "Mở đầu",
                    "paragraphs": [
                        {"id": f"par_{i:03d}", "text": f"Câu {i}.", "target_seconds": 5.0}
                        for i in range(paragraphs)
                    ],
                }
            ]
        }
    )


class _RecordingReasoner(ReasoningPort):
    """Returns a marked translation and records every prompt it was given."""

    def __init__(self, reply: str | None = None, model_name: str = "fake-reasoner") -> None:
        self.prompts: list[str] = []
        self.calls = 0
        self.model_name = model_name
        self._reply = reply

    @property
    def model(self) -> str:
        return self.model_name

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        self.prompts.append(prompt)
        self.calls += 1
        return (
            self._reply
            if self._reply is not None
            else json.dumps({"text": f"[translated] {prompt.split('text:')[-1].strip()[:40]}"})
        )

    def unload(self) -> None:
        return None


@dataclass
class _Ctx:
    conn: sqlite3.Connection
    ctx: StageContext
    reasoner: _RecordingReasoner


@pytest.fixture
def ctx(tmp_path: Path) -> _Ctx:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_t", input_file="m.mp4"))
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
        JobStatus.VISUAL_ANALYSIS_READY,
        JobStatus.CHARACTERS_READY,
        JobStatus.EVENTS_READY,
        JobStatus.STORY_READY,
        JobStatus.REVIEW_PLAN_READY,
        JobStatus.SCRIPT_READY,
    ):
        manager.transition("job_t", state)

    script = _script()
    script_path = source_script_path(tmp_path / "jobs", "job_t")
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        json.dumps({"job_id": "job_t", "script": script.model_dump(mode="json")}),
        encoding="utf-8",
    )

    stage_ctx = StageContext(
        job_id="job_t",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )
    return _Ctx(conn=conn, ctx=stage_ctx, reasoner=_RecordingReasoner())


def _translate(ctx: _Ctx, script: ReviewScript, **kwargs: Any) -> TranslationResult:
    options: dict[str, Any] = {
        "source_language": SOURCE,
        "target_language": TARGET,
        "spec": ModelSpec(model="fake-translator"),
        "reasoner": ctx.reasoner,
    }
    options.update(kwargs)
    return translate_script(script, ctx.ctx, **options)


# ---------------------------------------------------------------------------
# Language tags
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [("en", "en"), ("EN", "en"), ("  vi ", "vi"), ("pt-BR", "pt-br"), ("zh_Hans", "zh_hans")],
)
def test_tags_are_normalised(given: str, expected: str) -> None:
    assert validate_language(given) == expected


@pytest.mark.parametrize(
    "bad", ["", "e", "../../etc", "en/../x", "english_language_name", "en;DROP"]
)
def test_unusable_tags_are_rejected(bad: str) -> None:
    """The tag becomes a filename, so it cannot be anything unchecked."""
    with pytest.raises(TranslationError):
        validate_language(bad)


def test_same_language_needs_no_translation() -> None:
    assert needs_translation("en", "en") is False
    assert needs_translation("EN", " en ") is False


def test_different_languages_need_translation() -> None:
    assert needs_translation("vi", "en") is True
    assert needs_translation("en", "vi") is True


# ---------------------------------------------------------------------------
# The omitted-target case must do nothing at all
# ---------------------------------------------------------------------------


def test_omitted_target_is_a_no_op(ctx: _Ctx) -> None:
    """The requested default: target comes from language, so nothing is translated."""
    result = _translate(ctx, _script(), target_language=SOURCE)

    assert result.skipped is True
    assert result.script_path is None
    assert ctx.reasoner.calls == 0, "no model call for a same-language run"
    assert not translated_script_path(ctx.ctx.jobs_dir, "job_t", SOURCE).exists()


def test_no_op_leaves_the_source_as_the_effective_script(ctx: _Ctx) -> None:
    _translate(ctx, _script(), target_language=SOURCE)

    assert effective_script_path(ctx.ctx.jobs_dir, "job_t", SOURCE).name == "review-script.json"


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


def test_translation_replaces_paragraph_text(ctx: _Ctx) -> None:
    result = _translate(ctx, _script())

    assert result.skipped is False
    assert result.script_path is not None and result.script_path.is_file()
    texts = [p.text for s in result.script.sections for p in s.paragraphs]
    assert all(t != "Câu 0." for t in texts)
    assert result.translated_paragraphs == 2


def test_structure_is_preserved(ctx: _Ctx) -> None:
    """IDs and order are how subtitles and clips line up with the script."""
    result = _translate(ctx, _script(paragraphs=3))

    assert [s.id for s in result.script.sections] == ["sec_000"]
    assert [p.id for p in result.script.sections[0].paragraphs] == ["par_000", "par_001", "par_002"]


def test_source_script_is_left_intact(ctx: _Ctx) -> None:
    """The point of a separate file: the source stays translatable again."""
    original = [p.text for s in _script().sections for p in s.paragraphs]
    _translate(ctx, _script())

    reloaded = load_script(source_script_path(ctx.ctx.jobs_dir, "job_t"))
    assert [p.text for s in reloaded.sections for p in s.paragraphs] == original


def test_translated_file_is_named_for_the_language(ctx: _Ctx) -> None:
    result = _translate(ctx, _script())

    assert result.script_path is not None
    assert result.script_path.name == f"review-script.{TARGET}.json"


def test_effective_script_prefers_the_translation(ctx: _Ctx) -> None:
    _translate(ctx, _script())

    chosen = effective_script_path(ctx.ctx.jobs_dir, "job_t", TARGET)
    assert chosen.name == f"review-script.{TARGET}.json"
    assert load_script(chosen).sections[0].paragraphs[0].text != "Câu 0."


def test_effective_script_falls_back_when_absent(ctx: _Ctx) -> None:
    assert effective_script_path(ctx.ctx.jobs_dir, "job_t", TARGET).name == "review-script.json"


def test_document_records_both_languages(ctx: _Ctx) -> None:
    result = _translate(ctx, _script())

    assert result.script_path is not None
    document = json.loads(result.script_path.read_text(encoding="utf-8"))
    assert document["source_language"] == SOURCE
    assert document["target_language"] == TARGET


def test_artifact_is_recorded(ctx: _Ctx) -> None:
    _translate(ctx, _script())

    stored = repo.get_artifact(ctx.conn, f"job_t-review-script-{TARGET}")
    assert stored is not None
    assert stored.prompt_version is not None


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


def test_second_run_hits_the_cache(ctx: _Ctx) -> None:
    _translate(ctx, _script())
    calls_after_first = ctx.reasoner.calls

    second = _translate(ctx, _script())

    assert ctx.reasoner.calls == calls_after_first, "re-translated from scratch"
    assert second.cache_hits == 2
    assert second.translated_paragraphs == 0


def test_cache_is_keyed_on_the_target_language(ctx: _Ctx) -> None:
    """A different target must not reuse another target's text."""
    _translate(ctx, _script())
    calls = ctx.reasoner.calls

    _translate(ctx, _script(), target_language="fr")

    assert ctx.reasoner.calls == calls + 2


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_lost_evidence_marker_fails_the_paragraph(ctx: _Ctx) -> None:
    """INSUFFICIENT_EVIDENCE is a status code; losing it turns doubt into assertion."""
    script = ReviewScript.model_validate(
        {
            "sections": [
                {
                    "id": "sec_000",
                    "type": "intro",
                    "heading": "h",
                    "paragraphs": [
                        {
                            "id": "par_000",
                            "text": f"Diễn viên không xác nhận. {MARKER}",
                            "target_seconds": 5.0,
                        }
                    ],
                }
            ]
        }
    )
    ctx.reasoner = _RecordingReasoner(reply=json.dumps({"text": "The actor did not confirm."}))

    with pytest.raises(TranslationError, match=MARKER):
        _translate(ctx, script)


def test_a_kept_marker_passes(ctx: _Ctx) -> None:
    script = ReviewScript.model_validate(
        {
            "sections": [
                {
                    "id": "sec_000",
                    "type": "intro",
                    "heading": "h",
                    "paragraphs": [
                        {
                            "id": "par_000",
                            "text": f"Không rõ. {MARKER}",
                            "target_seconds": 5.0,
                        }
                    ],
                }
            ]
        }
    )
    ctx.reasoner = _RecordingReasoner(reply=json.dumps({"text": f"Unclear. {MARKER}"}))

    result = _translate(ctx, script)

    assert MARKER in result.script.sections[0].paragraphs[0].text


def test_empty_translation_is_rejected(ctx: _Ctx) -> None:
    ctx.reasoner = _RecordingReasoner(reply=json.dumps({"text": "   "}))

    with pytest.raises(TranslationError, match="empty"):
        _translate(ctx, _script())


def test_reply_without_a_text_field_is_rejected(ctx: _Ctx) -> None:
    ctx.reasoner = _RecordingReasoner(reply=json.dumps({"translated": "x"}))

    with pytest.raises(TranslationError, match="no text field"):
        _translate(ctx, _script())


def test_model_failure_is_classified(ctx: _Ctx) -> None:
    class _Boom(ReasoningPort):
        @property
        def model(self) -> str:
            return "fake"

        def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
            raise RuntimeError("HTTP 500")

        def unload(self) -> None:
            return None

    with pytest.raises(TranslationError, match="Translation call failed"):
        _translate(ctx, _script(), reasoner=_Boom())


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_stage_sits_between_review_and_tts() -> None:
    order = [name for name, _ in STAGE_SEQUENCE]
    assert order.index("review") < order.index("review-translate") < order.index("tts-chunks")


def test_stage_is_registered() -> None:
    assert _get_stage_function("review-translate") is not None


def _pipeline_ctx(tmp_path: Path, target: str) -> PipelineContext:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_w", input_file="m.mp4"))
    script_path = source_script_path(tmp_path / "jobs", "job_w")
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        json.dumps({"script": _script().model_dump(mode="json")}), encoding="utf-8"
    )
    return PipelineContext(
        job_id="job_w",
        movie_path=tmp_path / "m.mp4",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
        source_language=SOURCE,
        target_language=target,
    )


def test_downstream_stages_read_the_translated_script(tmp_path: Path) -> None:
    """The failure this prevents: narration and subtitles in the wrong language."""
    pipeline_ctx = _pipeline_ctx(tmp_path, TARGET)
    translated = translated_script_path(tmp_path / "jobs", "job_w", TARGET)
    translated.write_text(
        json.dumps(
            {
                "script": ReviewScript.model_validate(
                    {
                        "sections": [
                            {
                                "id": "sec_000",
                                "type": "intro",
                                "heading": "h",
                                "paragraphs": [
                                    {"id": "par_000", "text": "TRANSLATED", "target_seconds": 5.0}
                                ],
                            }
                        ]
                    }
                ).model_dump(mode="json")
            }
        ),
        encoding="utf-8",
    )

    script = load_effective_script(pipeline_ctx)

    assert script.sections[0].paragraphs[0].text == "TRANSLATED"


def test_downstream_stages_read_the_source_when_not_translated(tmp_path: Path) -> None:
    pipeline_ctx = _pipeline_ctx(tmp_path, SOURCE)

    script = load_effective_script(pipeline_ctx)

    assert script.sections[0].paragraphs[0].text == "Câu 0."


def test_transcript_receives_the_source_language() -> None:
    """--language used to be dropped on the floor, leaving ASR to guess."""
    import inspect

    from movie_review.pipeline import orchestrator

    source = inspect.getsource(orchestrator._get_stage_function)
    assert "language=ctx.source_language" in source


def test_context_defaults_target_to_source(tmp_path: Path) -> None:
    """An omitted target means the narration is spoken in the source language."""
    from movie_review.pipeline.orchestrator import _build_context

    built = _build_context("job_x", tmp_path / "m.mp4", str(tmp_path / "jobs.db"))

    assert built.target_language == built.source_language == "en"


# ---------------------------------------------------------------------------
# The dedicated translation model
# ---------------------------------------------------------------------------


def test_translation_slot_falls_back_to_reasoning() -> None:
    """A profile that does not declare one keeps its previous behaviour."""
    models = load_settings(profile="balanced").models

    assert models.translation is None
    assert models.effective_translation.model == models.reasoning.model


def test_translation_slot_is_independent_when_declared() -> None:
    """The whole point: swap the translator without touching reasoning."""
    models = ModelsSettings(
        asr=ModelSpec(model="asr"),
        vision=ModelSpec(model="vision"),
        reasoning=ModelSpec(model="Qwen3.5-27B"),
        critic=ModelSpec(model="critic"),
        tts=ModelSpec(model="tts"),
        translation=ModelSpec(model="Qwen3.5-9B"),
    )

    assert models.effective_translation.model == "Qwen3.5-9B"
    assert models.reasoning.model == "Qwen3.5-27B"


def test_every_shipped_profile_resolves_a_translation_model() -> None:
    for name in available_profiles():
        models = load_settings(profile=name).models
        assert models.effective_translation.model, name


def test_remote_profile_declares_its_own_translator() -> None:
    """The remote profile is the one a non-Apple host actually runs."""
    spec = load_settings(profile="remote").models.effective_translation

    assert spec.model != load_settings(profile="remote").models.reasoning.model


def test_translation_honours_the_configured_backend() -> None:
    """A remote translation endpoint must not be reached through MLX.

    Building the adapter by hand -- as this function used to -- ignored the
    backend and demanded mlx-vlm on every host.
    """
    from movie_review.reasoning.factory import build_reasoning_adapter

    spec = ModelSpec(
        model="translator",
        backend="openai_compatible",
        base_url="http://gpu:8000/v1",
    )
    adapter = build_reasoning_adapter(spec)

    assert type(adapter).__name__ == "OpenAICompatAdapter"
    assert adapter.model == "translator"


def test_the_stage_passes_the_translation_slot(tmp_path: Path) -> None:
    """Not the reasoning slot: that is the bug this slot exists to prevent."""
    import inspect

    from movie_review.pipeline import orchestrator

    source = inspect.getsource(orchestrator._get_stage_function)
    assert "effective_translation" in source
    assert "models.reasoning.model" not in source.split("review_translate_fn")[1].split("def ")[0]


def test_translation_model_identity_enters_the_cache_key(ctx: _Ctx) -> None:
    """Pointing at a different translator must not reuse the old one's output.

    The cache key uses the identity of the adapter that actually ran, which in
    production is the configured spec's model -- swap the translation model in
    models.yaml and every paragraph is translated again, rather than the new
    model silently inheriting the old model's cached prose.
    """
    _translate(ctx, _script())
    first_calls = ctx.reasoner.calls

    # A different adapter identity, same cache directory.
    ctx.reasoner = _RecordingReasoner(model_name="translator-b")
    second = _translate(ctx, _script())

    assert first_calls == 2
    assert second.cache_hits == 0, "reused another model's cached text"
    assert second.translated_paragraphs == 2
    assert ctx.reasoner.calls == 2


def test_same_model_reuses_the_cache(ctx: _Ctx) -> None:
    """The control: an unchanged configuration must still hit the cache."""
    _translate(ctx, _script())
    calls = ctx.reasoner.calls

    second = _translate(ctx, _script())

    assert second.cache_hits == 2
    assert ctx.reasoner.calls == calls
