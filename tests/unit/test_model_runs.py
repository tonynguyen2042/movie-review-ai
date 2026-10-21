"""Every model invocation has to be recorded.

T156. README §52 lists a `model_runs` table and §53 says every model
invocation shall record the model, the runtime, the stage, the prompt's
hash, the input and output tokens, the duration and the temperature -- and
calls it "essential for reproducibility". The table did not exist, the
adapters did not report their usage, and nothing was recorded.

Without it there is no way to answer "what produced this?" about a job that
has already finished.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from movie_review.domain import Job, ModelRun, ModelUsage
from movie_review.pipeline.model_runs import record_model_run
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


class _Adapter:
    """A reasoning adapter that reports its usage."""

    def __init__(self, usage: ModelUsage | None = None) -> None:
        self.usage = usage
        self.runtime_name = "remote"

    @property
    def runtime(self) -> str:
        return self.runtime_name

    def last_usage(self) -> ModelUsage | None:
        return self.usage

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        return "{}"

    def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
        return {}

    def unload(self) -> None:
        return None

    def available(self) -> bool:
        return True


def _db__model_runs(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    return conn


def test_the_table_exists(tmp_path: Path) -> None:
    """README section 52 lists a model_runs table; it did not exist."""
    conn = _db__model_runs(tmp_path)
    try:
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "model_runs" in names
    finally:
        conn.close()


def test_a_call_is_recorded(tmp_path: Path) -> None:
    conn = _db__model_runs(tmp_path)
    try:
        adapter = _Adapter(ModelUsage(input_tokens=120, output_tokens=45))
        with record_model_run(
            conn,
            "job_1",
            "review",
            adapter,
            "qwen3.5-27b",
            prompt_hash="abc123",
            prompt_version="script_writer:v1",
            temperature=0.4,
        ):
            adapter.complete_json("prompt")

        runs = repo.list_model_runs(conn, "job_1")
        assert len(runs) == 1
        run = runs[0]
        assert run.stage == "review"
        assert run.model == "qwen3.5-27b"
        assert run.runtime == "remote"
        assert run.prompt_hash == "abc123"
        assert run.prompt_version == "script_writer:v1"
        assert run.input_tokens == 120
        assert run.output_tokens == 45
        assert run.temperature == 0.4
        assert run.duration_ms >= 0
    finally:
        conn.close()


def test_a_call_that_reports_no_usage_is_still_recorded(tmp_path: Path) -> None:
    """A local runtime often cannot report the tokens; the call still counts."""
    conn = _db__model_runs(tmp_path)
    try:
        adapter = _Adapter(None)
        with record_model_run(conn, "job_1", "vision", adapter, "qwen3-vl"):
            adapter.complete_json("prompt")

        runs = repo.list_model_runs(conn, "job_1")
        assert len(runs) == 1
        assert runs[0].input_tokens is None
        assert runs[0].output_tokens is None
    finally:
        conn.close()


def test_a_failed_call_is_recorded_too(tmp_path: Path) -> None:
    """A run that died halfway is exactly when the record matters."""
    conn = _db__model_runs(tmp_path)
    try:
        adapter = _Adapter()
        with pytest.raises(RuntimeError):
            with record_model_run(conn, "job_1", "vision", adapter, "qwen3-vl"):
                raise RuntimeError("the model fell over")

        runs = repo.list_model_runs(conn, "job_1")
        assert len(runs) == 1
        assert runs[0].stage == "vision"
    finally:
        conn.close()


def test_the_runs_can_be_filtered_by_stage(tmp_path: Path) -> None:
    conn = _db__model_runs(tmp_path)
    try:
        for stage in ("review", "vision", "review"):
            with record_model_run(conn, "job_1", stage, _Adapter(), "m"):
                pass
        assert len(repo.list_model_runs(conn, "job_1")) == 3
        assert len(repo.list_model_runs(conn, "job_1", "review")) == 2
    finally:
        conn.close()


def test_the_remote_adapter_reports_the_usage_the_server_sent() -> None:
    """The counts come from the server, not from a guess."""
    from movie_review.reasoning.openai_compat import _usage_from

    usage = _usage_from({"usage": {"prompt_tokens": 100, "completion_tokens": 20}})
    assert usage is not None
    assert usage.input_tokens == 100
    assert usage.output_tokens == 20

    assert _usage_from({"usage": {}}) is None
    assert _usage_from({}) is None
    assert _usage_from("not a dict") is None


def test_the_model_run_round_trips(tmp_path: Path) -> None:
    conn = _db__model_runs(tmp_path)
    try:
        run = ModelRun(
            run_id="r1",
            job_id="job_1",
            stage="review",
            model="m",
            runtime="remote",
            prompt_hash="h",
            input_tokens=1,
            output_tokens=2,
            duration_ms=3,
            temperature=0.5,
        )
        repo.save_model_run(conn, "job_1", run)
        loaded = repo.list_model_runs(conn, "job_1")
        assert len(loaded) == 1
        assert loaded[0].input_tokens == 1
        assert loaded[0].duration_ms == 3
        assert loaded[0].temperature == 0.5
    finally:
        conn.close()
