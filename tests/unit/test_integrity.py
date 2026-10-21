"""T073 acceptance: job-level integrity scan detects missing/corrupt files."""

from pathlib import Path

import pytest

from movie_review.artifacts.integrity import (
    ArtifactRecord,
    scan_job_integrity,
    verify_or_raise,
)
from movie_review.artifacts.manager import ArtifactIntegrityError, sha256_bytes
from tests.helpers import (
    _write,
)


def test_scan_all_ok(tmp_path: Path) -> None:
    records = [_write(tmp_path, "ingest", "media.json", b"{}")]
    report = scan_job_integrity(tmp_path, "job1", records)
    assert report.passed and report.ok == 1


def test_scan_detects_corrupt_and_missing(tmp_path: Path) -> None:
    good = _write(tmp_path, "ingest", "media.json", b"{}")
    (tmp_path / "job1" / "ingest" / "media.json").write_bytes(b"tampered")
    missing = ArtifactRecord(relative_path="scenes/scenes.json", expected_hash="abc")
    report = scan_job_integrity(tmp_path, "job1", [good, missing])
    assert not report.passed
    assert report.corrupt == ["ingest/media.json"]
    assert report.missing == ["scenes/scenes.json"]


def test_a_file_at_the_job_root_is_verifiable(tmp_path: Path) -> None:
    """movie-analysis.json is written at the job root, not in a stage directory.

    The old stage-plus-filename shape had no way to express this, which is part of
    why validation could not find it.
    """
    target = tmp_path / "job1" / "movie-analysis.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"{}")

    report = scan_job_integrity(
        tmp_path,
        "job1",
        [ArtifactRecord(relative_path="movie-analysis.json", expected_hash=sha256_bytes(b"{}"))],
    )

    assert report.passed


def test_a_record_without_a_hash_is_checked_for_existence(tmp_path: Path) -> None:
    """Claiming a hash comparison that was never recorded would fail every file."""
    target = tmp_path / "job1" / "media" / "media.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"anything at all")

    report = scan_job_integrity(
        tmp_path, "job1", [ArtifactRecord(relative_path="media/media.json")]
    )

    assert report.passed
    assert report.ok == 1
    assert report.corrupt == []


def test_verify_or_raise(tmp_path: Path) -> None:
    records = [_write(tmp_path, "ingest", "media.json", b"{}")]
    assert verify_or_raise(tmp_path, "job1", records).passed
    (tmp_path / "job1" / "ingest" / "media.json").write_bytes(b"bad")
    with pytest.raises(ArtifactIntegrityError):
        verify_or_raise(tmp_path, "job1", records)
