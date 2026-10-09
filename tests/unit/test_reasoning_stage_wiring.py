"""Every reasoning stage must build its adapter from the configured ModelSpec.

Five stages took ``model: str`` and constructed ``QwenReasoningAdapter`` with it,
ignoring ``ModelSpec.backend``. Under ``--profile remote`` that demanded MLX on a
host with no Apple GPU, so the run died before reaching the story stage at all --
the same defect fixed for ASR in c4ad8f2, left unfixed here.

Each of them also derived the cache key from ``type(active).__name__`` for any
non-Qwen adapter. Every remote model then produced the identical key, so pointing
a run at a different model silently reused the previous model's output from cache.
The port already exposed ``.model``; these stages reached around it.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import ModelSpec, load_settings
from movie_review.domain import Event, EventType, Job
from movie_review.jobs.manager import JobManager
from movie_review.reasoning.port import ReasoningPort
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect

# (stage, module path, entry point, artifact id, a valid model response)
STAGES = {
    "arcs": (
        "movie_review.story.arcs",
        "movie_review.story.arcs:extract_story_arcs",
        "job_1-story-arcs",
        [
            {
                "element": "SETUP",
                "applicable": True,
                "description": "John receives the letter.",
                "event_ids": ["event_00001"],
                "confidence": 0.8,
            },
            {
                "element": "RESOLUTION",
                "applicable": False,
                "description": "",
                "event_ids": [],
                "confidence": 0.4,
            },
        ],
    ),
    "themes": (
        "movie_review.story.themes",
        "movie_review.story.themes:extract_themes",
        "job_1-themes",
        [
            {
                "theme": "trust",
                "evidence": ["event_00001"],
                "confidence": 0.7,
            }
        ],
    ),
    "twists": (
        "movie_review.story.twists",
        "movie_review.story.twists:extract_twists",
        "job_1-twists",
        [
            {
                "description": "Mary kept the letter.",
                "revealed_at": 90.0,
                # The stage requires at least two foreshadowing events: a twist
                # resting on a single mention is not evidenced.
                "foreshadowed_by": ["event_00001", "event_00002"],
                "confidence": 0.7,
            }
        ],
    ),
}


class _RecordingReasoner(ReasoningPort):
    """Fake that reports the model identity it was built with."""

    def __init__(self, model: str, outputs: Sequence[object]) -> None:
        self._model = model
        self._outputs = list(outputs)

    @property
    def model(self) -> str:
        return self._model

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        return json.dumps(self._outputs.pop(0))

    def unload(self) -> None:
        return None


def _remote_spec(model: str = "qwen3.5-27b") -> ModelSpec:
    return ModelSpec(
        model=model,
        backend="openai_compatible",
        base_url="http://192.168.1.144:8000/v1",
    )


def _conn(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    return conn


def _events() -> list[Event]:
    return [
        Event(
            id="event_00001",
            type=EventType.INTRODUCTION,
            timestamp=5.0,
            description="John receives a letter.",
            importance=0.9,
        ),
        Event(
            id="event_00002",
            type=EventType.CLIMAX,
            timestamp=90.0,
            description="Mary reveals she kept the letter.",
            importance=0.95,
        ),
    ]


def _import(target: str) -> Any:
    """Import ``package.module`` or ``package.module:attribute``."""
    import importlib

    module_name, _, attribute = target.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, attribute) if attribute else module


def _run(
    stage: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spec: ModelSpec,
    reasoner: ReasoningPort | None = None,
) -> tuple[Any, list[ModelSpec], str]:
    """Run one stage with the reasoning factory answering ``spec``.

    Returns the result, the specs the factory was asked for, and the model id the
    stage recorded on its artifact.
    """
    module, target, artifact_id, output = STAGES[stage]
    built: list[ModelSpec] = []
    active = reasoner or _RecordingReasoner(spec.model, [output])

    # Only patch when a reasoner was not supplied: a test that installs its own
    # factory assertion must not have it replaced here.
    if reasoner is None:

        def fake_build(given: ModelSpec) -> ReasoningPort:
            built.append(given)
            return active

        monkeypatch.setattr(f"{module}.build_reasoning_adapter", fake_build)

    conn = _conn(tmp_path)
    result = _import(target)(
        _events(),
        "char_001: John",
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        cache=CacheManager(tmp_path / "cache"),
        spec=spec,
        **({} if reasoner is None else {"reasoner": reasoner}),
    )
    artifact = repo.get_artifact(conn, artifact_id)
    conn.close()
    return result, built, artifact.model if artifact is not None else ""


# ---------------------------------------------------------------------------
# The configured backend reaches the stage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", list(STAGES))
def test_a_remote_backend_builds_a_remote_adapter(
    stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression: a remote profile must not construct the MLX adapter.

    Each of these stages called QwenReasoningAdapter(model) directly, so
    ``backend: openai_compatible`` was never consulted and the run demanded mlx-lm
    on a host with no Apple GPU.
    """
    spec = _remote_spec()

    _, built, _ = _run(stage, tmp_path, monkeypatch, spec)

    assert len(built) == 1
    assert built[0].backend == "openai_compatible"
    assert built[0].base_url == "http://192.168.1.144:8000/v1"
    assert built[0].model == "qwen3.5-27b"


@pytest.mark.parametrize("stage", list(STAGES))
def test_a_local_backend_is_still_honoured(
    stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apple Silicon hosts keep working: the default spec still reaches the factory."""
    _, built, _ = _run(stage, tmp_path, monkeypatch, ModelSpec(model="Qwen3.5-27B"))

    assert built[0].model == "Qwen3.5-27B"
    assert built[0].is_remote is False


# ---------------------------------------------------------------------------
# The cache key carries the model, not the class name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", list(STAGES))
def test_the_artifact_records_the_configured_model(
    stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproducibility needs the checkpoint that actually produced the output."""
    _, _, recorded = _run(stage, tmp_path, monkeypatch, _remote_spec())

    assert recorded == "qwen3.5-27b"


@pytest.mark.parametrize("stage", list(STAGES))
def test_different_models_record_different_model_ids(
    stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression for the cache key: two models, one key.

    ``type(active).__name__`` gave every remote adapter the key
    "OpenAICompatAdapter", so a run pointed at a different model would find the
    previous model's output already cached. That is precisely what the cache
    identity rules in AGENTS.md exist to prevent.
    """
    first = _run(stage, tmp_path / "a", monkeypatch, _remote_spec("qwen3.5-27b"))
    second = _run(stage, tmp_path / "b", monkeypatch, _remote_spec("llama-3.3-70b"))

    assert first[2] == "qwen3.5-27b"
    assert second[2] == "llama-3.3-70b"
    assert first[2] != second[2]


@pytest.mark.parametrize("stage", list(STAGES))
def test_a_different_model_does_not_hit_the_cache(
    stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same job, same cache directory, a different model: the stage must run."""
    _run(stage, tmp_path, monkeypatch, _remote_spec("qwen3.5-27b"))

    output = STAGES[stage][3]
    monkey_reasoner = _RecordingReasoner("llama-3.3-70b", [output])
    module, target, _, _ = STAGES[stage]

    def fake_build(given: ModelSpec) -> ReasoningPort:
        return monkey_reasoner

    monkeypatch.setattr(f"{module}.build_reasoning_adapter", fake_build)
    result = _import(target)(
        _events(),
        "char_001: John",
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=connect(tmp_path / "jobs.db"),
        cache=CacheManager(tmp_path / "cache"),
        spec=_remote_spec("llama-3.3-70b"),
    )

    assert result.cache_hit is False


@pytest.mark.parametrize("stage", list(STAGES))
def test_an_injected_reasoner_is_not_overridden(
    stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``reasoner`` is the seam for callers and tests that supply their own model."""
    module = STAGES[stage][0]

    def must_not_be_called(given: ModelSpec) -> ReasoningPort:
        raise AssertionError("the factory must not be consulted when a reasoner is given")

    monkeypatch.setattr(f"{module}.build_reasoning_adapter", must_not_be_called)

    reasoner = _RecordingReasoner("injected-model", [STAGES[stage][3]])
    _, built, recorded = _run(stage, tmp_path, monkeypatch, _remote_spec(), reasoner)

    assert built == []
    assert recorded == "injected-model"


# ---------------------------------------------------------------------------
# The same defect in the two stages that read their spec from settings
# ---------------------------------------------------------------------------


def test_event_extraction_honours_the_configured_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """events takes no model argument; it must read the spec off ctx.settings.

    It read ``ctx.settings.models.reasoning.model`` -- the name -- and handed it
    to QwenReasoningAdapter, so the configured backend never applied.
    """
    from movie_review.domain import Character, JobStatus, Scene, SceneAnalysis
    from movie_review.pipeline.context import StageContext
    from movie_review.story import events as events_module

    spec = _remote_spec()
    built: list[ModelSpec] = []

    def fake_build(given: ModelSpec) -> ReasoningPort:
        built.append(given)
        return _RecordingReasoner(given.model, [[_event_output()]])

    monkeypatch.setattr("movie_review.story.events.build_reasoning_adapter", fake_build)

    base = load_settings()
    settings = base.model_copy(
        update={"models": base.models.model_copy(update={"reasoning": spec})}
    )
    conn = _conn(tmp_path)
    manager = JobManager(conn)
    for status in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
        JobStatus.VISUAL_ANALYSIS_READY,
        JobStatus.CHARACTERS_READY,
    ):
        manager.transition("job_1", status)

    scene = Scene(scene_id="scene_000001", start=0.0, end=5.0, duration=5.0)
    analysis = SceneAnalysis(
        scene_id="scene_000001",
        location="office",
        actions=["John reads a letter"],
    )
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=settings,
        conn=conn,
    )

    events_module.run_event_extraction(
        [scene],
        {scene.scene_id: analysis},
        [],
        [Character(id="char_001", name="John", first_seen=0.0, last_seen=5.0)],
        ctx,
    )

    assert len(built) == 1
    assert built[0].is_remote is True
    assert built[0].model == "qwen3.5-27b"


def test_event_extraction_records_the_model_not_the_class_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache key half of the same defect, for the events stage."""
    from movie_review.domain import Character, JobStatus, Scene, SceneAnalysis
    from movie_review.pipeline.context import StageContext
    from movie_review.story import events as events_module

    def fake_build(given: ModelSpec) -> ReasoningPort:
        return _RecordingReasoner(given.model, [[_event_output()]])

    monkeypatch.setattr("movie_review.story.events.build_reasoning_adapter", fake_build)

    base = load_settings()
    spec = _remote_spec()
    settings = base.model_copy(
        update={"models": base.models.model_copy(update={"reasoning": spec})}
    )
    conn = _conn(tmp_path)
    manager = JobManager(conn)
    for status in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
        JobStatus.VISUAL_ANALYSIS_READY,
        JobStatus.CHARACTERS_READY,
    ):
        manager.transition("job_1", status)

    scene = Scene(scene_id="scene_000001", start=0.0, end=5.0, duration=5.0)
    analysis = SceneAnalysis(
        scene_id="scene_000001", location="office", actions=["John reads a letter"]
    )
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=settings,
        conn=conn,
    )

    events_module.run_event_extraction(
        [scene],
        {scene.scene_id: analysis},
        [],
        [Character(id="char_001", name="John", first_seen=0.0, last_seen=5.0)],
        ctx,
    )

    recorded = repo.list_artifacts(conn, "job_1")
    event_artifacts = [a for a in recorded if a.stage == "events"]
    assert event_artifacts
    assert all(a.model == "qwen3.5-27b" for a in event_artifacts)


def test_review_writer_honours_the_configured_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """write_script takes a spec and must build from it, not from a model name."""
    from movie_review.domain import JobStatus
    from movie_review.pipeline.context import StageContext
    from movie_review.review.styles import load_style
    from movie_review.review.writer import write_script

    spec = _remote_spec()
    built: list[ModelSpec] = []

    def fake_build(given: ModelSpec) -> ReasoningPort:
        built.append(given)
        return _RecordingReasoner(given.model, [_section_output()])

    monkeypatch.setattr("movie_review.review.writer.build_reasoning_adapter", fake_build)

    conn = _conn(tmp_path)
    manager = JobManager(conn)
    for status in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
        JobStatus.VISUAL_ANALYSIS_READY,
        JobStatus.CHARACTERS_READY,
        JobStatus.EVENTS_READY,
        JobStatus.STORY_READY,
    ):
        manager.transition("job_1", status)

    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )

    # An empty outline means no section prompts, so the fake reasoner is never
    # called; what matters here is which adapter the stage asked for.
    write_script(
        _empty_plan(),
        {"characters": [], "events": [], "relationships": []},
        load_style("youtube"),
        100,
        ctx,
        spec=spec,
    )

    assert len(built) == 1
    assert built[0].is_remote is True
    assert built[0].model == "qwen3.5-27b"


def _empty_plan() -> Any:
    """A minimal valid plan.

    ReviewPlan requires at least one section, so this is not empty -- it simply
    produces no narration, which is all this test needs: which adapter the stage
    asked for.
    """
    from movie_review.domain import ReviewPlan

    return ReviewPlan.model_validate(
        {
            "sections": [
                {
                    "id": "sec_00001",
                    "type": "INTRO",
                    "target_seconds": 30,
                    "event_ids": [],
                    "purpose": "Introduce the film.",
                }
            ],
            "total_seconds": 30,
        }
    )


def _section_output() -> dict[str, Any]:
    """One narration section, in the shape the writer expects."""
    return {
        "sections": [
            {
                "id": "sec_00001",
                "type": "INTRO",
                "paragraphs": [
                    {
                        "id": "para_00001",
                        "text": "The film opens in an office.",
                        "target_seconds": 30,
                    }
                ],
            }
        ]
    }


def _event_output() -> dict[str, Any]:
    return {
        "type": "CONFLICT",
        "timestamp": 10.0,
        "description": "John confronts Mary.",
        "characters": ["char_001"],
        "evidence": ["scene_000001"],
        "importance": 0.8,
    }


def test_the_factory_still_builds_the_local_adapter_for_a_local_spec() -> None:
    """Guards the change: the default profile is untouched."""
    from movie_review.reasoning.factory import build_reasoning_adapter

    adapter = build_reasoning_adapter(ModelSpec(model="Qwen3.5-27B"))

    assert type(adapter).__name__ == "QwenReasoningAdapter"


def test_no_production_stage_constructs_the_mlx_adapter_directly() -> None:
    """Only the factory may choose an adapter from a backend decision.

    A stage reaching for QwenReasoningAdapter cannot honour ``backend``, which is
    the whole defect; this pins that so it cannot come back unnoticed.
    """
    import re

    offenders: list[str] = []
    for path in Path("src/movie_review").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name in {"factory.py", "qwen.py", "__init__.py"}:
            continue
        # Ignore prose: only a construction counts.
        for match in re.finditer(r"QwenReasoningAdapter\s*\(", text):
            offenders.append(f"{path}: {match.group(0)}")

    assert offenders == []
