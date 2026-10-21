"""The second pass: a critic reads the finished script and reports on it.

README section 35 asks for an optional high-quality mode: a second model
reads the finished script and judges its coherence, its hook, its pacing, its
unsupported claims and its conclusion, and proposes rewrites. It is not for
every scene -- it is for the script, once, at the end.

The ``critic`` model slot existed in the configuration and the ``quality``
profile enabled it, but nothing ever built a critic adapter, so the quality
profile behaved exactly like balanced.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from movie_review.config.prompts import load_prompt, render
from movie_review.config.settings import ModelSpec
from movie_review.domain import ReviewScript
from movie_review.pipeline.context import StageContext
from movie_review.reasoning.factory import build_reasoning_adapter
from movie_review.reasoning.port import ReasoningPort
from movie_review.storage import repositories as repo
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

STAGE_NAME = "critic"
STAGE_VERSION = "v1"
CRITIC_FILENAME = "critic-report.json"

#: The kinds of problem the critic reports.
ISSUE_KINDS = (
    "hook",
    "coherence",
    "pacing",
    "unsupported_claim",
    "repetition",
    "conclusion",
)

#: The severities the critic reports.
SEVERITIES = ("minor", "moderate", "major")


class CriticError(Exception):
    """The critic failed in a classified way."""


@dataclass(frozen=True)
class CriticIssue:
    """One problem the critic found."""

    kind: str
    severity: str
    section_id: str
    detail: str

    def model_dump(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "section_id": self.section_id,
            "detail": self.detail,
        }


@dataclass
class CritiqueResult:
    """The critic's report."""

    issues: list[CriticIssue] = field(default_factory=list)
    summary: str = ""
    model: str = ""
    skipped: bool = False
    duration_ms: int = 0


def parse_critique(raw: Any) -> tuple[list[CriticIssue], str]:
    """Read the critic's answer.

    An issue the critic did not name a valid kind or severity for is dropped
    rather than reported: a malformed report is not a reason to fail the
    review, and a report with a wrong shape is the model's mistake, not the
    script's.
    """
    if not isinstance(raw, dict):
        return [], ""
    summary = raw.get("summary")
    summary = summary.strip() if isinstance(summary, str) else ""

    issues: list[CriticIssue] = []
    raw_issues = raw.get("issues")
    if not isinstance(raw_issues, list):
        return issues, summary
    for entry in raw_issues:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        severity = entry.get("severity")
        section_id = entry.get("section_id")
        detail = entry.get("detail")
        if kind not in ISSUE_KINDS or severity not in SEVERITIES:
            continue
        if not isinstance(section_id, str) or not isinstance(detail, str):
            continue
        issues.append(
            CriticIssue(
                kind=kind,
                severity=severity,
                section_id=section_id,
                detail=detail.strip(),
            )
        )
    return issues, summary


def critique_script(
    script: ReviewScript,
    ctx: StageContext,
    spec: ModelSpec,
    *,
    reasoner: ReasoningPort | None = None,
    prompt_version: str | None = None,
) -> CritiqueResult:
    """Read the finished script and report on it.

    The critic is optional: a profile that does not enable it, or a
    configuration that disables it, gets an empty report rather than a
    failure. The ``quality`` profile enables it; ``fast`` and ``balanced``
    do not, and README section 35 is explicit that this model is not for
    every scene.
    """
    started = time.perf_counter()
    if not spec.enabled:
        return CritiqueResult(
            skipped=True,
            summary="The critic is not enabled for this profile.",
        )

    prompt = load_prompt("critic", prompt_version)
    active = reasoner or build_reasoning_adapter(spec)
    sections = [
        {
            "id": section.id,
            "type": section.type,
            "paragraphs": [
                {"id": paragraph.id, "text": paragraph.text} for paragraph in section.paragraphs
            ],
        }
        for section in script.sections
    ]
    text = render(
        prompt,
        style="",
        target_words=str(sum(len(p.text.split()) for s in script.sections for p in s.paragraphs)),
        sections=json.dumps(sections, indent=2),
    )

    try:
        raw = active.complete_json(text)
    except Exception as exc:
        raise CriticError(f"Cannot critique the script: {exc}") from exc
    finally:
        active.unload()

    issues, summary = parse_critique(raw)
    duration_ms = int((time.perf_counter() - started) * 1000)

    document = {
        "job_id": ctx.job_id,
        "stage": STAGE_NAME,
        "stage_version": STAGE_VERSION,
        "model": spec.model,
        "issues": [issue.model_dump() for issue in issues],
        "summary": summary,
    }
    from movie_review.artifacts import manager as artifacts

    report_path = artifacts.artifact_path(ctx.jobs_dir, ctx.job_id, STAGE_NAME, CRITIC_FILENAME)
    output_hash = artifacts.write_json(report_path, document)
    repo.save_artifact(
        ctx.conn,
        __import__("movie_review.domain", fromlist=["Artifact"]).Artifact(
            artifact_id=f"{ctx.job_id}-critic",
            job_id=ctx.job_id,
            stage=STAGE_NAME,
            relative_path=artifacts.relative_artifact_path(ctx.jobs_dir, ctx.job_id, report_path),
            input_hash=output_hash,
            output_hash=output_hash,
            model=spec.model,
        ),
    )

    with ulog.logging_context(job_id=ctx.job_id, stage=STAGE_NAME):
        ulog.log_event(
            _logger,
            event="critic.completed",
            status="ok",
            duration_ms=duration_ms,
            issues=len(issues),
        )

    return CritiqueResult(
        issues=issues,
        summary=summary,
        model=spec.model,
        duration_ms=duration_ms,
    )
