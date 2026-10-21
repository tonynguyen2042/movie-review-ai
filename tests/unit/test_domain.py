"""T004 acceptance: domain contracts validate and round-trip."""

import pytest
from pydantic import ValidationError

from movie_review.domain import (
    Artifact,
    Claim,
    ClaimStatus,
    ClaimType,
    Evidence,
    EvidenceType,
    Job,
    JobStatus,
    Movie,
    MovieMetadata,
    Scene,
)


def _scene__domain() -> Scene:
    return Scene(scene_id="scene_000123", start=1532.21, end=1549.82, duration=17.61)


def test_scene_valid_chronology() -> None:
    scene = _scene__domain()
    assert scene.duration == pytest.approx(17.61)


def test_scene_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        Scene(scene_id="s", start=10.0, end=5.0, duration=5.0)


def test_scene_rejects_duration_mismatch() -> None:
    with pytest.raises(ValidationError):
        Scene(scene_id="s", start=10.0, end=15.0, duration=4.0)


def _metadata(**overrides: object) -> MovieMetadata:
    data: dict[str, object] = {
        "file": "movie.mp4",
        "sha256": "a" * 64,
        "duration_seconds": 7200.0,
        "width": 1920,
        "height": 1080,
        "fps": 24.0,
        "video_codec": "h264",
    }
    data.update(overrides)
    return MovieMetadata.model_validate(data)


def test_movie_metadata_validates() -> None:
    movie = Movie(id="m1", metadata=_metadata())
    assert movie.metadata.sha256 == "a" * 64
    with pytest.raises(ValidationError):
        Movie(id="m2", metadata=_metadata(sha256="short"))


def test_evidence_confidence_bounded() -> None:
    Evidence(id="e1", type=EvidenceType.DIALOGUE, source_id="seg_1", confidence=0.9)
    with pytest.raises(ValidationError):
        Evidence(id="e2", type=EvidenceType.VISUAL, source_id="f1", confidence=1.5)


def test_claim_defaults_to_insufficient_evidence() -> None:
    claim = Claim(claim_id="c1", text="Sarah knew.", type=ClaimType.PLOT_FACT)
    assert claim.status == ClaimStatus.INSUFFICIENT_EVIDENCE
    assert claim.evidence == []


def test_job_defaults_to_created() -> None:
    job = Job(job_id="j1", input_file="movie.mp4")
    assert job.status == JobStatus.CREATED
    assert job.retry_count == 0


def test_artifact_requires_identity() -> None:
    artifact = Artifact(artifact_id="a1", job_id="j1", stage="ingest", input_hash="h")
    assert artifact.version == 1
    with pytest.raises(ValidationError):
        Artifact(artifact_id="a2", job_id="j1", stage="ingest", input_hash="")


def test_models_round_trip_json() -> None:
    scene = _scene__domain()
    assert Scene.model_validate_json(scene.model_dump_json()) == scene
    claim = Claim(claim_id="c1", text="t", type=ClaimType.OPINION)
    assert Claim.model_validate(claim.model_dump()) == claim


def test_spec_enums_complete() -> None:
    assert {e.value for e in EvidenceType} == {
        "DIALOGUE",
        "VISUAL",
        "AUDIO",
        "SCENE",
        "EVENT",
        "CHARACTER",
        "TIMELINE",
    }
    assert JobStatus.COMPLETED.value == "COMPLETED"
    assert JobStatus.FAILED.value == "FAILED"
