"""The second pass must read the finished script and report on it.

T159. README section 35 asks for an optional high-quality mode: a second
model reads the finished script and judges its coherence, its hook, its
pacing, its unsupported claims and its conclusion. The `critic` model slot
existed in the configuration and the `quality` profile enabled it, but
nothing ever built a critic adapter — so the quality profile behaved
exactly like balanced.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import ModelSpec, load_settings
from movie_review.domain import (
    Job,
    JobStatus,
    ReviewParagraph,
    ReviewScript,
    ReviewSection,
)
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.reasoning.port import ReasoningPort
from movie_review.review.critic import (
    CriticError,
    critique_script,
    parse_critique,
)
from movie_review.storage.database import bootstrap, connect


class _StubReasoner(ReasoningPort):
    """A reasoning adapter that answers with a fixed document."""

    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.prompts: list[str] = []
        self.unloaded = 0

    @property
    def model(self) -> str:
        return "stub"

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        self.prompts.append(prompt)
        return "{}"

    def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
        self.prompts.append(prompt)
        return self.answer

    def unload(self) -> None:
        self.unloaded += 1

    def available(self) -> bool:
        return True


def _ctx__critic(tmp_path: Path) -> tuple[StageContext, sqlite3.Connection]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo_job = Job(job_id="job_1", input_file="m.mp4")
    conn.execute(
        "INSERT INTO jobs (job_id, input_file, status, failed_stage, error, "
        "retry_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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


def _script__critic() -> ReviewScript:
    return ReviewScript(
        sections=[
            ReviewSection(
                id="sec_001",
                type="hook",
                paragraphs=[
                    ReviewParagraph(
                        id="p1",
                        text="The hero walks into the room.",
                        target_seconds=10,
                        claims=[],
                        visual_intent="s",
                    )
                ],
            )
        ]
    )


def test_the_prompt_exists() -> None:
    """The prompt follows the section 63 contract."""
    from movie_review.config.prompts import load_prompt

    prompt = load_prompt("critic")
    for section in ("ROLE:", "INPUT:", "TASK:", "CONSTRAINTS:", "OUTPUT:", "FAILURE BEHAVIOR:"):
        assert section in prompt.template, f"the prompt has no {section}"


def test_the_prompt_is_registered() -> None:
    assert "critic" in load_settings().prompts.versions


def test_a_disabled_critic_is_skipped(tmp_path: Path) -> None:
    """A profile that does not enable it gets an empty report."""
    ctx, conn = _ctx__critic(tmp_path)
    try:
        spec = ModelSpec(model="qwen3.5-122b", enabled=False)
        result = critique_script(_script__critic(), ctx, spec)
        assert result.skipped is True
        assert result.issues == []
    finally:
        conn.close()


def test_the_critic_reports_the_issues(tmp_path: Path) -> None:
    ctx, conn = _ctx__critic(tmp_path)
    try:
        reasoner = _StubReasoner(
            {
                "issues": [
                    {
                        "kind": "hook",
                        "severity": "major",
                        "section_id": "sec_001",
                        "detail": "The hook never sets up the ending.",
                    }
                ],
                "summary": "The hook does not pay off.",
            }
        )
        result = critique_script(
            _script__critic(),
            ctx,
            ModelSpec(model="qwen3.5-122b"),
            reasoner=reasoner,
        )
        assert len(result.issues) == 1
        assert result.issues[0].kind == "hook"
        assert result.issues[0].severity == "major"
        assert result.summary == "The hook does not pay off."
        assert reasoner.prompts, "the critic was never asked"
        assert reasoner.unloaded == 1
    finally:
        conn.close()


def test_the_report_is_written(tmp_path: Path) -> None:
    ctx, conn = _ctx__critic(tmp_path)
    try:
        critique_script(
            _script__critic(),
            ctx,
            ModelSpec(model="qwen3.5-122b"),
            reasoner=_StubReasoner({"issues": [], "summary": "It works."}),
        )
        report = Path(ctx.jobs_dir) / "job_1" / "critic" / "critic-report.json"
        assert report.is_file()
    finally:
        conn.close()


def test_a_malformed_issue_is_dropped() -> None:
    """A report with a wrong shape is the model's mistake, not the script's."""
    issues, summary = parse_critique(
        {
            "issues": [
                {"kind": "not_a_kind", "severity": "major", "section_id": "s", "detail": "x"},
                {"kind": "hook", "severity": "not_a_severity", "section_id": "s", "detail": "x"},
                {"kind": "hook", "severity": "minor", "section_id": "s", "detail": "x"},
                "not an object",
            ],
            "summary": "A summary.",
        }
    )
    assert len(issues) == 1
    assert issues[0].kind == "hook"
    assert summary == "A summary."


def test_a_clean_script_is_not_padded_with_issues() -> None:
    issues, summary = parse_critique({"issues": [], "summary": "It works."})
    assert issues == []
    assert summary == "It works."


def test_a_failing_critic_is_reported(tmp_path: Path) -> None:
    ctx, conn = _ctx__critic(tmp_path)
    try:

        class _Broken(_StubReasoner):
            def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
                raise RuntimeError("the model fell over")

        with pytest.raises(CriticError):
            critique_script(
                _script__critic(),
                ctx,
                ModelSpec(model="qwen3.5-122b"),
                reasoner=_Broken({}),
            )
    finally:
        conn.close()
