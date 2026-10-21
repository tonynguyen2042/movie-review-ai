"""tts-concat must actually join the chunks (T105).

The stage was ``pass``. Everything around it was finished -- plan_chunks,
synthesize_chunk, concatenate, measure_wav -- so the pipeline walked past an
empty stage and then died in tts-reconcile with

    Cannot measure .../tts/narration.wav

on a file that was never written. These tests run the real stage function over
real chunk files.

Concatenation re-derives the chunk plan rather than receiving results in memory,
because it is a separately retryable stage. That only works if both stages agree
on the inputs, so the voice is a shared constant and there is a test saying why.
"""

from __future__ import annotations

import json
import sqlite3
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from movie_review.artifacts import manager as artifacts
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus, ReviewScript
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.orchestrator import PipelineContext, _get_stage_function, run_stage
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.tts.chunks import (
    DEFAULT_VOICE,
    ChunkCollectionError,
    TTSChunk,
    collect_chunk_results,
    plan_chunks,
)
from movie_review.tts.concat import (
    NARRATION_FILENAME,
    ConcatError,
    ConcatResult,
    concatenate,
)


def _script(paragraphs: int = 2) -> ReviewScript:
    return ReviewScript.model_validate(
        {
            "sections": [
                {
                    "id": "sec_000",
                    "type": "intro",
                    "heading": "Intro",
                    "paragraphs": [
                        {
                            "id": f"par_{i:03d}",
                            "text": f"Paragraph number {i}.",
                            "target_seconds": 5.0,
                        }
                        for i in range(paragraphs)
                    ],
                }
            ]
        }
    )


@dataclass
class _Ctx:
    conn: sqlite3.Connection
    ctx: PipelineContext
    script_path: Path


@pytest.fixture
def ctx(tmp_path: Path) -> _Ctx:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_c", input_file="m.mp4"))
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
        manager.transition("job_c", state)

    jobs_dir = tmp_path / "jobs"
    script_path = jobs_dir / "job_c" / "review" / "review-script.json"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        json.dumps({"script": _script().model_dump(mode="json")}), encoding="utf-8"
    )

    return _Ctx(
        conn=conn,
        ctx=PipelineContext(
            job_id="job_c",
            movie_path=tmp_path / "m.mp4",
            jobs_dir=jobs_dir,
            conn=conn,
            manager=manager,
            cache=CacheManager(tmp_path / "cache"),
            settings=load_settings(),
        ),
        script_path=script_path,
    )


def _stage() -> Callable[[PipelineContext], Any]:
    stage = _get_stage_function("tts-concat")
    assert stage is not None, "tts-concat is missing from the orchestrator"
    return stage


def _write_chunk(path: Path, seconds: float = 1.0, rate: int = 16000) -> None:
    """Write a silent WAV of a known length."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * int(seconds * rate))


def _write_all_chunks(ctx: _Ctx, script: ReviewScript | None = None, seconds: float = 1.0) -> None:
    for chunk in plan_chunks(script or _script(), voice=DEFAULT_VOICE):
        _write_chunk(
            artifacts.artifact_path(ctx.ctx.jobs_dir, "job_c", "tts", f"{chunk.chunk_id}.wav"),
            seconds,
        )


# ---------------------------------------------------------------------------
# The stage produces a narration file
# ---------------------------------------------------------------------------


def test_stage_writes_narration(ctx: _Ctx) -> None:
    """The file tts-reconcile goes on to measure now exists."""
    _write_all_chunks(ctx)

    result = _stage()(ctx.ctx)

    assert isinstance(result, ConcatResult)
    narration = ctx.ctx.jobs_dir / "job_c" / "tts" / NARRATION_FILENAME
    assert narration.is_file()
    assert result.duration_seconds == pytest.approx(2.0, abs=0.01)


def test_narration_length_is_the_sum_of_its_chunks(ctx: _Ctx) -> None:
    _write_all_chunks(ctx)

    result = _stage()(ctx.ctx)

    with wave.open(str(result.path), "rb") as wav:
        measured = wav.getnframes() / wav.getframerate()
    assert measured == pytest.approx(result.duration_seconds, abs=0.01)
    assert result.segments and len(result.segments) == 2


def test_metadata_names_every_paragraph(ctx: _Ctx) -> None:
    """The sidecar is what later stages use to map audio back to text."""
    _write_all_chunks(ctx)

    result = _stage()(ctx.ctx)

    assert result.metadata_path.is_file()
    document = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    ids = [segment["paragraph_id"] for segment in document["segments"]]
    assert ids == ["par_000", "par_001"]
    assert all(segment["voice"] == DEFAULT_VOICE for segment in document["segments"])


def test_segment_durations_match_their_own_files(ctx: _Ctx) -> None:
    """Each sidecar entry must describe the audio it sits beside.

    Durations are measured from the files, so a chunk that was replaced by a
    different length is reported at its real length rather than a recorded one.
    A total cannot prove ordering -- reversing the files leaves the sum
    unchanged -- so the ordering claim is made where it is observable, on the
    paragraph sequence in the metadata.
    """
    script = _script(paragraphs=3)
    ctx.script_path.write_text(
        json.dumps({"script": script.model_dump(mode="json")}), encoding="utf-8"
    )
    expected: dict[str, float] = {}
    # The chunk id is content-derived, so the position comes from the plan.
    for index, chunk in enumerate(plan_chunks(script, voice=DEFAULT_VOICE)):
        seconds = 1.0 + index
        expected[chunk.paragraph_id] = seconds
        _write_chunk(
            artifacts.artifact_path(ctx.ctx.jobs_dir, "job_c", "tts", f"{chunk.chunk_id}.wav"),
            seconds=seconds,
        )

    result = _stage()(ctx.ctx)

    assert [s["paragraph_id"] for s in result.segments] == list(expected)
    assert [s["duration"] for s in result.segments] == pytest.approx(
        list(expected.values()), abs=0.01
    )
    assert result.duration_seconds == pytest.approx(sum(expected.values()), abs=0.01)


# ---------------------------------------------------------------------------
# A missing chunk must stop the stage, not shorten the narration
# ---------------------------------------------------------------------------


def test_missing_chunk_fails_the_stage(ctx: _Ctx) -> None:
    _write_all_chunks(ctx)
    planned = plan_chunks(_script(paragraphs=2), voice=DEFAULT_VOICE)
    missing = artifacts.artifact_path(
        ctx.ctx.jobs_dir, "job_c", "tts", f"{planned[1].chunk_id}.wav"
    )
    missing.unlink()

    stage_result = run_stage("tts-concat", _stage(), ctx.ctx)

    assert stage_result.success is False
    assert planned[1].chunk_id in (stage_result.error or "")


def test_narration_is_not_written_when_a_chunk_is_missing(ctx: _Ctx) -> None:
    """No partial narration: a short file is worse than none."""
    _write_all_chunks(ctx)
    planned = plan_chunks(_script(paragraphs=2), voice=DEFAULT_VOICE)
    narration = ctx.ctx.jobs_dir / "job_c" / "tts" / NARRATION_FILENAME
    artifacts.artifact_path(ctx.ctx.jobs_dir, "job_c", "tts", f"{planned[1].chunk_id}.wav").unlink()

    run_stage("tts-concat", _stage(), ctx.ctx)

    assert not narration.exists()


def test_missing_narration_was_what_broke_reconcile(ctx: _Ctx) -> None:
    """The reported symptom, pinned as a regression."""
    _write_all_chunks(ctx)
    assert not (ctx.ctx.jobs_dir / "job_c" / "tts" / NARRATION_FILENAME).exists()

    run_stage("tts-concat", _stage(), ctx.ctx)

    from movie_review.tts.reconcile import measure_wav

    measured = measure_wav(ctx.ctx.jobs_dir / "job_c" / "tts" / NARRATION_FILENAME)
    assert measured > 0


# ---------------------------------------------------------------------------
# collect_chunk_results
# ---------------------------------------------------------------------------


def test_collect_measures_rather_than_trusting_a_record(ctx: _Ctx) -> None:
    script = _script(paragraphs=2)
    planned = plan_chunks(script, voice=DEFAULT_VOICE)
    _write_all_chunks(ctx, script, seconds=2.5)

    results = collect_chunk_results(planned, ctx.ctx.jobs_dir, "job_c")

    assert [r.duration_seconds for r in results] == pytest.approx([2.5, 2.5], abs=0.01)
    assert [r.chunk.chunk_id for r in results] == [c.chunk_id for c in planned]


def test_collect_rejects_an_empty_plan(ctx: _Ctx) -> None:
    with pytest.raises(ChunkCollectionError, match="no chunks"):
        collect_chunk_results([], ctx.ctx.jobs_dir, "job_c")


def test_collect_names_the_missing_paragraph(ctx: _Ctx) -> None:
    planned = plan_chunks(_script(paragraphs=2), voice=DEFAULT_VOICE)
    _write_all_chunks(ctx)

    artifacts.artifact_path(ctx.ctx.jobs_dir, "job_c", "tts", f"{planned[1].chunk_id}.wav").unlink()

    with pytest.raises(ChunkCollectionError) as excinfo:
        collect_chunk_results(planned, ctx.ctx.jobs_dir, "job_c")

    # The second paragraph is the one that is missing.
    assert "par_001" in str(excinfo.value)
    assert planned[1].chunk_id in str(excinfo.value)


def test_planning_is_deterministic(ctx: _Ctx) -> None:
    """Both stages re-plan, so the IDs have to come out identical."""
    first = plan_chunks(_script(paragraphs=3), voice=DEFAULT_VOICE)
    second = plan_chunks(_script(paragraphs=3), voice=DEFAULT_VOICE)

    assert first == second
    # The ids are content-derived, so the plan is what carries the order.
    assert [c.paragraph_id for c in first] == ["par_000", "par_001", "par_002"]


def test_voice_constant_is_shared_by_both_stages() -> None:
    """Two literal strings would drift, and the metadata would start lying."""
    from movie_review.tts import chunks as chunks_module

    assert DEFAULT_VOICE == "default"
    assert DEFAULT_VOICE is chunks_module.DEFAULT_VOICE


def test_concat_rejects_mismatched_chunk_formats(ctx: _Ctx, tmp_path: Path) -> None:
    """Loudly, rather than producing audio that plays at the wrong speed."""
    planned = plan_chunks(_script(paragraphs=2), voice=DEFAULT_VOICE)
    _write_all_chunks(ctx)
    _write_chunk(
        artifacts.artifact_path(ctx.ctx.jobs_dir, "job_c", "tts", f"{planned[1].chunk_id}.wav"),
        seconds=1.0,
        rate=8000,
    )

    results = collect_chunk_results(planned, ctx.ctx.jobs_dir, "job_c")

    with pytest.raises(ConcatError, match="Parameter mismatch"):
        concatenate(results, tmp_path / "narration.wav")


def test_collected_results_expose_the_chunk_metadata(ctx: _Ctx) -> None:
    planned: list[TTSChunk] = plan_chunks(_script(), voice=DEFAULT_VOICE)
    _write_all_chunks(ctx)

    results = collect_chunk_results(planned, ctx.ctx.jobs_dir, "job_c")

    assert results[0].chunk.paragraph_id == "par_000"
    assert results[0].path.is_file()
