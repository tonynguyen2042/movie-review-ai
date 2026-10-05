"""T073 acceptance: job-level integrity scan detects missing/corrupt files."""

from pathlib import Path

import pytest

from movie_review.artifacts.integrity import (
    ArtifactRecord,
    scan_job_integrity,
    verify_or_raise,
)
from movie_review.artifacts.manager import ArtifactIntegrityError, sha256_bytes


def _write(root: Path, stage: str, name: str, data: bytes) -> ArtifactRecord:
    target = root / "job1" / stage / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return ArtifactRecord(stage=stage, filename=name, expected_hash=sha256_bytes(data))


def test_scan_all_ok(tmp_path: Path) -> None:
    records = [_write(tmp_path, "ingest", "media.json", b"{}")]
    report = scan_job_integrity(tmp_path, "job1", records)
    assert report.passed and report.ok == 1


def test_scan_detects_corrupt_and_missing(tmp_path: Path) -> None:
    good = _write(tmp_path, "ingest", "media.json", b"{}")
    (tmp_path / "job1" / "ingest" / "media.json").write_bytes(b"tampered")
    missing = ArtifactRecord(stage="scenes", filename="scenes.json", expected_hash="abc")
    report = scan_job_integrity(tmp_path, "job1", [good, missing])
    assert not report.passed
    assert report.corrupt == ["ingest/media.json"]
    assert report.missing == ["scenes/scenes.json"]


def test_verify_or_raise(tmp_path: Path) -> None:
    records = [_write(tmp_path, "ingest", "media.json", b"{}")]
    assert verify_or_raise(tmp_path, "job1", records).passed
    (tmp_path / "job1" / "ingest" / "media.json").write_bytes(b"bad")
    with pytest.raises(ArtifactIntegrityError):
        verify_or_raise(tmp_path, "job1", records)
