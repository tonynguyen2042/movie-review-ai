"""Ground truth annotations (T079).

Typed schema plus loader/validator for hand-checked golden annotations:
canonical events, characters, and claim verdicts. Validation fails loudly
on unknown IDs so drift between fixtures and annotations cannot pass
silently.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GroundTruthClaim(BaseModel):
    """One hand-checked claim with its expected verdict."""

    claim_id: str
    text: str
    type: str = "PLOT_FACT"
    evidence: list[str] = Field(default_factory=list)
    verdict: str = "SUPPORTED"


class GroundTruth(BaseModel):
    """Hand-checked expectations for one golden movie."""

    movie_id: str
    event_ids: list[str] = Field(default_factory=list)
    character_ids: list[str] = Field(default_factory=list)
    claims: list[GroundTruthClaim] = Field(default_factory=list)


class GroundTruthError(Exception):
    """Annotations are malformed or inconsistent with fixtures."""


def load_ground_truth(payload: dict[str, Any]) -> GroundTruth:
    """Parse and validate a ground-truth payload."""
    try:
        return GroundTruth.model_validate(payload)
    except Exception as exc:
        raise GroundTruthError(f"Invalid ground truth: {exc}") from exc


def validate_against_analysis(ground_truth: GroundTruth, analysis: dict[str, Any]) -> None:
    """Raise unless every annotated ID exists in the analysis document."""
    analysis_events = {event.get("id") for event in analysis.get("events", [])}
    analysis_chars = {char.get("id") for char in analysis.get("characters", [])}
    analysis_evidence = {item.get("id") for item in analysis.get("evidence", [])}
    missing_events = set(ground_truth.event_ids) - analysis_events
    missing_chars = set(ground_truth.character_ids) - analysis_chars
    missing_evidence = {
        evidence_id for claim in ground_truth.claims for evidence_id in claim.evidence
    } - analysis_evidence
    problems = []
    if missing_events:
        problems.append(f"unknown events: {sorted(missing_events)}")
    if missing_chars:
        problems.append(f"unknown characters: {sorted(missing_chars)}")
    if missing_evidence:
        problems.append(f"unknown evidence: {sorted(missing_evidence)}")
    if problems:
        raise GroundTruthError("; ".join(problems))
