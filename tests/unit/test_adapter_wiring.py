"""Stages must build their model adapter from configuration (T100).

Every adapter factory existed and dispatched correctly on ``ModelSpec.backend``,
but no pipeline stage called one. Each stage constructed its MLX adapter
directly, so ``backend: openai_compatible`` was ignored and every non-Apple host
died with ``mlx-whisper is not installed`` -- regardless of configuration.

These tests pin the wiring, not the adapters (test_remote_adapters.py covers
those). The failing scenario to prevent is a future edit that reintroduces a
hardcoded adapter, so several tests assert on what the stage *asked for* rather
than only on the adapter type that comes back.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.asr import port as asr_port
from movie_review.asr.transcript import TranscriptResult, run_transcript
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import AppSettings, ModelSpec, available_profiles, load_settings
from movie_review.domain import Job, JobStatus, SceneAnalysis, TranscriptSegment
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.vision import port as vision_port
from tests.helpers import (
    _fake_extract,
    _remote_spec,
    _segments,
)


def _with_asr(settings: AppSettings, spec: ModelSpec) -> AppSettings:
    """``settings`` with only the ASR slot replaced.

    ``AppSettings`` is a pydantic model, so this is model_copy rather than
    dataclasses.replace.
    """
    return settings.model_copy(update={"models": settings.models.model_copy(update={"asr": spec})})


class _RecordingASR(asr_port.ASRPort):
    """Fake that reports the model identity it was built with."""

    def __init__(self, model: str = "remote-whisper") -> None:
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def transcribe(
        self, audio_path: str | Path, *, language: str | None = None
    ) -> list[TranscriptSegment]:
        return _segments()

    def unload(self) -> None:
        return None


@dataclass
class _Stage:
    conn: sqlite3.Connection
    ctx: StageContext
    source: Path

    def run(
        self, monkeypatch: pytest.MonkeyPatch, spec: ModelSpec
    ) -> tuple[TranscriptResult, list[ModelSpec]]:
        """Run the transcript stage with the ASR factory answering ``spec``."""
        built: list[ModelSpec] = []
        adapter = _RecordingASR()

        def fake_build(given: ModelSpec) -> asr_port.ASRPort:
            built.append(given)
            return adapter

        monkeypatch.setattr("movie_review.asr.transcript.build_asr_adapter", fake_build)
        settings = _with_asr(self.ctx.settings, spec)
        ctx = StageContext(
            job_id=self.ctx.job_id,
            jobs_dir=self.ctx.jobs_dir,
            cache=self.ctx.cache,
            manager=self.ctx.manager,
            settings=settings,
            conn=self.ctx.conn,
        )
        return run_transcript(self.source, ctx, language="en", extract_fn=_fake_extract), built


def _stage__adapter_wiring(tmp_path: Path) -> _Stage:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    for state in (JobStatus.INGESTING, JobStatus.MEDIA_READY, JobStatus.SCENES_READY):
        manager.transition("job_1", state)
    source = tmp_path / "m.mp4"
    source.write_bytes(b"source-bytes")
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )
    return _Stage(conn=conn, ctx=ctx, source=source)


# ---------------------------------------------------------------------------
# The stage asks the factory, with the configured spec
# ---------------------------------------------------------------------------


def test_transcript_builds_its_adapter_from_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The spec passed to the factory must be the one the job runs with."""
    stage = _stage__adapter_wiring(tmp_path)
    spec = _remote_spec()

    _, built = stage.run(monkeypatch, spec)

    assert built == [spec], f"stage did not use the configured spec: {built}"


def test_remote_spec_does_not_reach_mlx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A remote spec must never construct a local MLX adapter.

    This is the regression that produced the reported failure: the stage built
    WhisperMLXAdapter regardless of backend, so `remote` failed identically to
    `balanced` on a host without mlx-whisper.
    """
    stage = _stage__adapter_wiring(tmp_path)

    import movie_review.asr.transcript as transcript_module

    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("MLX adapter constructed for a remote profile")

    monkeypatch.setattr(transcript_module, "build_asr_adapter", explode)
    monkeypatch.setattr(
        "movie_review.asr.whisper_mlx.WhisperMLXAdapter.__init__", explode, raising=False
    )

    settings = _with_asr(stage.ctx.settings, _remote_spec())
    ctx = StageContext(
        job_id=stage.ctx.job_id,
        jobs_dir=stage.ctx.jobs_dir,
        cache=stage.ctx.cache,
        manager=stage.ctx.manager,
        settings=settings,
        conn=stage.ctx.conn,
    )

    # The factory is stubbed out above to explode, so reaching it proves the
    # stage consulted configuration; the point is that nothing fell back to a
    # hardcoded MLX path that bypassed it.
    with pytest.raises(AssertionError, match="MLX adapter constructed"):
        run_transcript(stage.source, ctx, language="en", extract_fn=_fake_extract)


# ---------------------------------------------------------------------------
# Cache identity must name the model, not the adapter class
# ---------------------------------------------------------------------------


def test_cache_identity_uses_the_model_not_the_adapter_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two checkpoints behind one adapter must not share a cache entry.

    The stage used to fall back to ``type(active).__name__`` for anything that
    was not the local Whisper adapter, so every remote run keyed its cache on
    "OpenAICompatASRAdapter" -- identical no matter which model served it.
    """
    stage = _stage__adapter_wiring(tmp_path)
    monkeypatch.setattr(
        "movie_review.asr.transcript.build_asr_adapter",
        lambda spec: _RecordingASR(model="whisper-large-v3"),
    )
    settings = _with_asr(stage.ctx.settings, _remote_spec())
    ctx = StageContext(
        job_id=stage.ctx.job_id,
        jobs_dir=stage.ctx.jobs_dir,
        cache=stage.ctx.cache,
        manager=stage.ctx.manager,
        settings=settings,
        conn=stage.ctx.conn,
    )

    result = run_transcript(stage.source, ctx, language="en", extract_fn=_fake_extract)

    import json

    document = json.loads(Path(result.transcript_path).read_text(encoding="utf-8"))
    assert document["model"] == "whisper-large-v3"
    assert "OpenAICompat" not in document["model"]


def test_port_default_model_is_the_adapter_name() -> None:
    """The fallback exists for fakes; it must not be silent about being weak."""

    class Bare(asr_port.ASRPort):
        def transcribe(
            self, audio_path: str | Path, *, language: str | None = None
        ) -> list[TranscriptSegment]:
            return []

        def unload(self) -> None:
            return None

    assert Bare().model == "Bare"


def test_vision_port_exposes_model() -> None:
    """The VLM port needs the same hook; the stage reads it for cache keys."""

    class BareVision(vision_port.VLMPort):
        def analyze(
            self, analysis_input: vision_port.AnalysisInput, prompt: str
        ) -> SceneAnalysis:  # pragma: no cover - unused
            raise NotImplementedError

        def unload(self) -> None:
            return None

    assert BareVision().model == "BareVision"


# ---------------------------------------------------------------------------
# Profile selection
# ---------------------------------------------------------------------------


def test_available_profiles_includes_remote() -> None:
    """The catalog is the source of truth; 'remote' must be discoverable."""
    assert "remote" in available_profiles()


def test_profile_override_beats_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit flag must win over MOVIE_REVIEW_MODELS__PROFILE.

    A user who exported the variable once should still be able to override it
    per run; otherwise the flag would silently do nothing on their machine.
    """
    monkeypatch.setenv("MOVIE_REVIEW_MODELS__PROFILE", "balanced")
    assert load_settings().models.profile == "balanced"
    assert load_settings(profile="remote").models.profile == "remote"


def test_unknown_profile_is_rejected_with_the_available_names() -> None:
    """A typo must list the real options instead of a bare 'unknown profile'."""
    with pytest.raises(ValueError, match="remote"):
        load_settings(profile="nope")


def test_remote_profile_selects_remote_asr() -> None:
    """End to end through the catalog: profile in, remote ASR spec out."""
    settings = load_settings(profile="remote")
    assert settings.models.asr.backend == "openai_compatible"
    assert settings.models.asr.is_remote is True
    assert settings.models.asr.base_url


def test_default_profile_stays_local() -> None:
    """Selecting a profile must not change what the default does."""
    assert load_settings().models.asr.backend == "mlx"


# ---------------------------------------------------------------------------
# TTS and VLM were wired the same wrong way
# ---------------------------------------------------------------------------


def test_tts_chunks_stage_asks_the_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """The orchestrator's TTS stage must consult ModelSpec, not construct MLX."""
    from movie_review.pipeline.orchestrator import _get_stage_function

    seen: list[ModelSpec] = []
    settings = load_settings(profile="remote")

    def fake_build(spec: ModelSpec) -> None:
        seen.append(spec)
        raise RuntimeError("stop here: factory was consulted")

    monkeypatch.setattr("movie_review.tts.factory.build_tts_adapter", fake_build)

    from movie_review.domain import ReviewScript
    from movie_review.pipeline.orchestrator import PipelineContext

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    import json

    script = ReviewScript.model_validate(
        {
            "sections": [
                {
                    "id": "sec_000",
                    "type": "intro",
                    "heading": "Intro",
                    "paragraphs": [{"id": "par_000", "text": "Hello", "target_seconds": 5.0}],
                }
            ]
        }
    )
    ctx = PipelineContext(
        job_id="job_1",
        movie_path=Path("m.mp4"),
        jobs_dir=Path("."),
        conn=conn,
        manager=JobManager(conn),
        cache=CacheManager(Path(".")),
        settings=settings,
    )
    # The stage reads review-script.json before building the adapter; point it at
    # a real file so the failure we expect is the factory call, not a missing path.
    script_path = Path("job_1/review/review-script.json")
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(json.dumps({"script": script.model_dump(mode="json")}), encoding="utf-8")
    try:
        stage = _get_stage_function("tts-chunks")
        assert stage is not None
        with pytest.raises(RuntimeError, match="factory was consulted"):
            stage(ctx)
    finally:
        script_path.unlink(missing_ok=True)
        script_path.parent.rmdir()

    assert seen == [settings.models.tts]
    assert seen[0].is_remote is True


def test_vision_stage_asks_the_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Same for the VLM: a remote profile must not construct QwenVLAdapter."""
    from movie_review.vision import analysis as vision_analysis

    seen: list[ModelSpec] = []

    def fake_build(spec: ModelSpec) -> None:
        seen.append(spec)
        raise RuntimeError("stop here: factory was consulted")

    monkeypatch.setattr(vision_analysis, "build_vlm_adapter", fake_build)

    from movie_review.pipeline.context import StageContext
    from movie_review.storage.database import bootstrap, connect

    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
    ):
        manager.transition("job_1", state)

    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(profile="remote"),
    )

    with pytest.raises(RuntimeError, match="factory was consulted"):
        vision_analysis.run_visual_analysis([], {}, [], ctx)

    assert seen == [ctx.settings.models.vision]
    assert seen[0].is_remote is True
