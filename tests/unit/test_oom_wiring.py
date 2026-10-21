"""A memory-pressure failure must release the model and try again.

T149. `models/resources.py::run_with_oom_recovery` was complete and tested,
and no stage used it. The constitution's P8 requires the system to detect
memory pressure, release the model, clear the cache, reduce the workload
and retry. A 4K source on a 128 GB box simply crashed the run instead of
degrading.

The four stages that call a model -- the vision analysis, the transcript,
the TTS chunker and the review writer -- now recover.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus
from movie_review.jobs.manager import JobManager
from movie_review.models.resources import OOMRecoveryError, is_oom, run_with_oom_recovery
from movie_review.pipeline.context import StageContext
from movie_review.storage.database import bootstrap, connect


class _FlakyPort:
    """A port that fails with memory pressure once, then succeeds."""

    def __init__(self, error: Exception | None = None, always: bool = False) -> None:
        self.error = error
        self.always = always
        self.calls = 0
        self.unloads = 0

    def _work(self) -> str:
        self.calls += 1
        if self.error is not None and (self.always or self.calls == 1):
            raise self.error
        return "done"

    def unload(self) -> None:
        self.unloads += 1

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        return self._work()

    def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
        return self._work()

    def available(self) -> bool:
        return True


def test_the_recovery_releases_the_model_and_retries() -> None:
    """The mechanism existed; no stage called it."""
    port = _FlakyPort(RuntimeError("MPS out of memory"))
    result = run_with_oom_recovery(
        lambda: port.complete_json("prompt"), port.unload, attempts=2, stage="test"
    )
    assert result == "done"
    assert port.calls == 2
    assert port.unloads == 1, "the model was not released"


def test_a_persistent_oom_is_reported() -> None:
    """Two attempts, then the failure surfaces."""
    port = _FlakyPort(RuntimeError("CUDA out of memory"), always=True)
    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        run_with_oom_recovery(
            lambda: port.complete_json("prompt"), port.unload, attempts=2, stage="test"
        )
    assert port.calls == 2


def test_a_non_oom_failure_is_not_retried() -> None:
    """A schema violation is not a memory problem."""
    port = _FlakyPort(ValueError("the prompt does not match the schema"))
    with pytest.raises(ValueError):
        run_with_oom_recovery(
            lambda: port.complete_json("prompt"), port.unload, attempts=2, stage="test"
        )
    assert port.calls == 1
    assert port.unloads == 0


def test_a_failed_release_is_reported() -> None:
    """A release that fails is a classified failure, not a hang."""
    port = _FlakyPort(RuntimeError("out of memory"))

    def boom() -> None:
        raise RuntimeError("the unload itself failed")

    with pytest.raises(OOMRecoveryError, match="Unload failed"):
        run_with_oom_recovery(lambda: port.complete_json("prompt"), boom, attempts=2, stage="test")


def test_the_oom_detection_covers_the_common_phrasings() -> None:
    assert is_oom(MemoryError()) is True
    assert is_oom(RuntimeError("MPS out of memory")) is True
    assert is_oom(RuntimeError("cannot allocate memory")) is True
    assert is_oom(ValueError("bad schema")) is False


def _ctx(tmp_path: Path) -> tuple[StageContext, sqlite3.Connection]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo_job = Job(job_id="job_1", input_file="m.mp4")
    conn.execute(
        "INSERT INTO jobs (job_id, input_file, status, failed_stage, error, retry_count, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            repo_job.job_id,
            repo_job.input_file,
            JobStatus.CREATED.value,
            None,
            None,
            0,
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ),
    )
    conn.commit()
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
    )
    return ctx, conn


def test_the_stages_call_the_recovery() -> None:
    """The recovery module was written and nothing used it."""
    from movie_review.pipeline import orchestrator

    source = Path(orchestrator.__file__).read_text(encoding="utf-8")
    # The orchestrator reaches the stages; the stages themselves are what
    # have to recover.
    for module in (
        "src/movie_review/vision/analysis.py",
        "src/movie_review/asr/transcript.py",
        "src/movie_review/tts/chunks.py",
        "src/movie_review/review/writer.py",
    ):
        text = Path(module).read_text(encoding="utf-8")
        assert "run_with_oom_recovery" in text, f"{module} does not recover from an OOM"
