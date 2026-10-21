"""Pipeline orchestrator: stage sequencing, failure handling, context wiring.

The orchestrator previously had no tests and referenced functions that do not
exist (``characters.linking.link_characters``, ``repositories.get_clip``), so
those code paths could only fail at runtime. These tests cover the pieces that
are safe to exercise without models or FFmpeg.
"""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.pipeline.orchestrator import (
    STAGE_SEQUENCE,
    PipelineContext,
    StageResult,
    _build_context,
    _get_stage_function,
    run_pipeline,
    run_stage,
)
from movie_review.storage.database import bootstrap


def _ctx(tmp_path: Path) -> PipelineContext:
    settings = load_settings()
    db = tmp_path / "jobs.db"
    conn = sqlite3.connect(str(bootstrap(db)))
    conn.row_factory = sqlite3.Row
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    return PipelineContext(
        job_id="job_test",
        jobs_dir=jobs_dir,
        conn=conn,
        manager=JobManager(conn),
        cache=CacheManager(tmp_path / "cache"),
        settings=settings,
        movie_path=tmp_path / "movie.mp4",
    )


def _stub_context(
    tmp_path: Path,
) -> Callable[..., PipelineContext]:
    """Stand in for _build_context, accepting whatever kwargs it is called with.

    Defined once rather than as a lambda per test: the real signature grows an
    option every time a run-level setting is threaded through, and a lambda that
    does not match it fails as a TypeError in five unrelated tests.
    """

    def _build(
        job_id: str,
        movie_path: str | Path,
        db_path: str | None,
        profile: str | None = None,
        source_language: str | None = None,
        target_language: str | None = None,
        generation: object = None,
    ) -> PipelineContext:
        return _ctx(tmp_path)

    return _build


# ---------------------------------------------------------------------------
# context wiring
# ---------------------------------------------------------------------------


def test_pipeline_context_is_a_stage_context() -> None:
    """It must be passable to any stage without conversion."""
    ctx = _ctx(Path("/tmp"))
    assert isinstance(ctx, StageContext)


def test_pipeline_context_exposes_stage_fields() -> None:
    """Every StageContext field is present."""
    ctx = _ctx(Path("/tmp"))
    for field in ("job_id", "jobs_dir", "cache", "manager", "settings", "conn"):
        assert hasattr(ctx, field)


def test_build_context_uses_jobs_subdirectory(tmp_path, monkeypatch) -> None:
    """jobs_dir must be <data_dir>/jobs, matching StageContext.from_settings.

    Regression: it used to be the bare data_dir, so artifacts would have been
    written to data/<job_id>/ instead of data/jobs/<job_id>/.
    """

    data_dir = tmp_path / "data"
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "models.yaml").write_text(
        "profiles:\n"
        "  balanced:\n"
        "    asr: {model: w}\n"
        "    vision: {model: v}\n"
        "    reasoning: {model: r}\n"
        "    critic: {model: c}\n"
        "    tts: {model: t}\n",
        encoding="utf-8",
    )
    (cfg / "default.yaml").write_text(
        f"paths:\n  data_dir: {data_dir}\nprompts:\n  versions:\n    scene_analysis: v1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MOVIE_REVIEW_CONFIG", str(cfg / "default.yaml"))

    ctx = _build_context("job_x", tmp_path / "movie.mp4", str(tmp_path / "jobs.db"))
    assert ctx.jobs_dir == data_dir / "jobs"
    assert isinstance(ctx.jobs_dir, Path)
    assert isinstance(ctx.movie_path, Path)


# ---------------------------------------------------------------------------
# run_stage
# ---------------------------------------------------------------------------


def test_run_stage_reports_success() -> None:
    ctx = _ctx(Path("/tmp"))
    result = run_stage("demo", lambda c: "ok", ctx)
    assert isinstance(result, StageResult)
    assert result.stage == "demo"
    assert result.success is True
    assert result.error is None
    assert result.duration_ms >= 0


def test_run_stage_captures_failure_without_raising() -> None:
    """A failing stage returns a result instead of propagating."""
    ctx = _ctx(Path("/tmp"))

    def boom(c: PipelineContext) -> None:
        raise ValueError("kaboom")

    result = run_stage("demo", boom, ctx)
    assert result.success is False
    assert "kaboom" in (result.error or "")


def test_run_stage_measures_duration() -> None:
    import time

    ctx = _ctx(Path("/tmp"))

    def slow(c: PipelineContext) -> None:
        time.sleep(0.01)

    assert run_stage("demo", slow, ctx).duration_ms >= 5


# ---------------------------------------------------------------------------
# stage registry
# ---------------------------------------------------------------------------


def test_stage_sequence_is_ordered_and_unique() -> None:
    names = [name for name, _ in STAGE_SEQUENCE]
    assert names[0] == "ingest"
    assert names[-1] == "quality"
    assert len(names) == len(set(names))


@pytest.mark.parametrize("stage_name,_desc", STAGE_SEQUENCE)
def test_every_stage_has_a_function(stage_name: str, _desc: str) -> None:
    """No stage in the sequence is a dead entry."""
    assert callable(_get_stage_function(stage_name))


def test_unknown_stage_returns_none() -> None:
    assert _get_stage_function("does-not-exist") is None


def test_stage_function_references_resolve() -> None:
    """Every name the closures import must actually exist.

    Regression: characters_fn imported a nonexistent link_characters.
    """
    import importlib

    module_file = importlib.import_module("movie_review.pipeline.orchestrator").__file__
    assert module_file is not None
    src = Path(module_file).read_text(encoding="utf-8")

    from movie_review.characters import linking
    from movie_review.storage import repositories

    assert not hasattr(linking, "link_characters")
    assert "link_characters(" not in src
    assert not hasattr(repositories, "get_clip")
    assert "repo.get_clip" not in src
    assert "repositories.get_clip" not in src


# ---------------------------------------------------------------------------
# sequencing
# ---------------------------------------------------------------------------


def test_run_pipeline_stops_at_first_failure(monkeypatch, tmp_path) -> None:
    """Execution halts on failure so later stages never run on bad state."""
    calls: list[str] = []

    monkeypatch.setattr(
        "movie_review.pipeline.orchestrator._build_context",
        _stub_context(tmp_path),
    )

    def fake_registry(stage_name: str) -> Any:
        def run(ctx: PipelineContext) -> str:
            calls.append(stage_name)
            if stage_name == "scenes":
                raise RuntimeError("scene detection failed")
            return stage_name

        return run

    monkeypatch.setattr("movie_review.pipeline.orchestrator._get_stage_function", fake_registry)

    results = run_pipeline("job_test", tmp_path / "movie.mp4")
    assert [r.stage for r in results] == ["ingest", "scenes"]
    assert results[-1].success is False
    assert "scene detection failed" in (results[-1].error or "")
    assert calls == ["ingest", "scenes"]


def test_run_pipeline_runs_all_stages(monkeypatch, tmp_path) -> None:
    """A healthy run visits every stage in order."""
    calls: list[str] = []
    monkeypatch.setattr(
        "movie_review.pipeline.orchestrator._build_context",
        _stub_context(tmp_path),
    )

    def registry(stage_name: str) -> Any:
        def run(ctx: PipelineContext) -> str:
            calls.append(stage_name)
            return stage_name

        return run

    monkeypatch.setattr("movie_review.pipeline.orchestrator._get_stage_function", registry)

    results = run_pipeline("job_test", tmp_path / "movie.mp4")
    assert [r.stage for r in results] == [n for n, _ in STAGE_SEQUENCE]
    assert all(r.success for r in results)


def test_run_pipeline_respects_start_and_end(monkeypatch, tmp_path) -> None:
    """Stage-range execution runs only the requested window."""
    monkeypatch.setattr(
        "movie_review.pipeline.orchestrator._build_context",
        _stub_context(tmp_path),
    )
    monkeypatch.setattr(
        "movie_review.pipeline.orchestrator._get_stage_function",
        lambda name: lambda ctx: name,
    )

    results = run_pipeline(
        "job_test", tmp_path / "movie.mp4", start_stage="scenes", end_stage="vision"
    )
    assert [r.stage for r in results] == ["scenes", "transcript", "vision"]


def test_run_pipeline_empty_when_start_after_end(monkeypatch, tmp_path) -> None:
    """An impossible range runs nothing rather than everything."""
    monkeypatch.setattr(
        "movie_review.pipeline.orchestrator._build_context",
        _stub_context(tmp_path),
    )
    monkeypatch.setattr(
        "movie_review.pipeline.orchestrator._get_stage_function",
        lambda name: lambda ctx: name,
    )
    results = run_pipeline(
        "job_test", tmp_path / "movie.mp4", start_stage="quality", end_stage="ingest"
    )
    assert results == []


def test_run_pipeline_end_stage_is_inclusive(monkeypatch, tmp_path) -> None:
    """Regression: the end stage used to be skipped entirely."""
    monkeypatch.setattr(
        "movie_review.pipeline.orchestrator._build_context",
        _stub_context(tmp_path),
    )
    monkeypatch.setattr(
        "movie_review.pipeline.orchestrator._get_stage_function",
        lambda name: lambda ctx: name,
    )
    results = run_pipeline(
        "job_test", tmp_path / "movie.mp4", start_stage="scenes", end_stage="scenes"
    )
    assert [r.stage for r in results] == ["scenes"]


def test_run_pipeline_rejects_unknown_stage(monkeypatch, tmp_path) -> None:
    """A typo in a stage name fails loudly instead of running nothing."""
    monkeypatch.setattr(
        "movie_review.pipeline.orchestrator._build_context",
        _stub_context(tmp_path),
    )
    with pytest.raises(ValueError, match="Unknown start stage"):
        run_pipeline("job_test", tmp_path / "movie.mp4", start_stage="scnes")
    with pytest.raises(ValueError, match="Unknown end stage"):
        run_pipeline("job_test", tmp_path / "movie.mp4", end_stage="qualityy")


# ---------------------------------------------------------------------------
# characters stage regression
# ---------------------------------------------------------------------------


def test_discover_characters_receives_a_list() -> None:
    """The signature the orchestrator calls requires a list, not a dict.

    Guards the fix for discover_characters(analyses_dict, ...).
    """
    import inspect

    from movie_review.characters.discovery import discover_characters

    params = inspect.signature(discover_characters).parameters
    assert params["analyses"].annotation == "list[SceneAnalysis]"
    assert not params["analyses"].annotation.startswith("dict")
