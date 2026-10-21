"""The path guards have to be proven, not assumed.

T166. `artifacts/manager.py::resolve_relative` was never called directly.
Only the `../..` case was covered, and only indirectly through
`scan_job_integrity`, so an absolute path and a Windows drive path were
never proven to be rejected.

`relative_artifact_path` never raised in any test either, so a stage that
wrote outside the job root would have recorded a path that later could not
be validated — and nothing would have said so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from movie_review.artifacts.manager import (
    UnsafePathError,
    artifact_path,
    relative_artifact_path,
    resolve_relative,
)

# --- resolve_relative ----------------------------------------------------


def test_a_nested_relative_path_resolves(tmp_path: Path) -> None:
    resolved = resolve_relative(tmp_path, "job_1", "render/review.mp4")
    assert resolved == tmp_path / "job_1" / "render" / "review.mp4"


def test_an_absolute_path_is_rejected(tmp_path: Path) -> None:
    """A tampered row must not make a validator read an arbitrary file."""
    with pytest.raises(UnsafePathError):
        resolve_relative(tmp_path, "job_1", "/etc/passwd")


def test_a_windows_drive_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_relative(tmp_path, "job_1", "C:/Windows/System32/config")


def test_a_parent_segment_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_relative(tmp_path, "job_1", "../../etc/passwd")


def test_a_parent_segment_in_the_middle_is_rejected(tmp_path: Path) -> None:
    """A path that only escapes halfway is still an escape."""
    with pytest.raises(UnsafePathError):
        resolve_relative(tmp_path, "job_1", "render/../../../etc/passwd")


def test_an_empty_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError, match="Empty artifact path"):
        resolve_relative(tmp_path, "job_1", "")


def test_a_path_of_only_slashes_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        resolve_relative(tmp_path, "job_1", "///")


def test_an_unsafe_job_id_is_rejected(tmp_path: Path) -> None:
    """The job id is a path segment too."""
    with pytest.raises(UnsafePathError):
        resolve_relative(tmp_path, "../elsewhere", "render/review.mp4")


# --- relative_artifact_path ----------------------------------------------


def test_a_path_inside_the_job_root_is_recorded(tmp_path: Path) -> None:
    path = tmp_path / "job_1" / "render" / "review.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"video")
    relative = relative_artifact_path(tmp_path, "job_1", path)
    assert relative == "render/review.mp4"


def test_a_path_outside_the_job_root_is_rejected(tmp_path: Path) -> None:
    """A stage that wrote outside the job root has to be told so."""
    elsewhere = tmp_path / "elsewhere" / "artifact.json"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text("{}", encoding="utf-8")
    with pytest.raises(UnsafePathError, match="not inside the job root"):
        relative_artifact_path(tmp_path, "job_1", elsewhere)


def test_a_path_in_another_job_is_rejected(tmp_path: Path) -> None:
    """One job's artifact is not another job's."""
    path = tmp_path / "job_2" / "render" / "review.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"video")
    with pytest.raises(UnsafePathError):
        relative_artifact_path(tmp_path, "job_1", path)


# --- artifact_path --------------------------------------------------------


def test_artifact_path_rejects_an_unsafe_segment(tmp_path: Path) -> None:
    for job_id, stage, filename in (
        ("../elsewhere", "render", "review.mp4"),
        ("job_1", "../render", "review.mp4"),
        ("job_1", "render", "../review.mp4"),
    ):
        with pytest.raises(UnsafePathError):
            artifact_path(tmp_path, job_id, stage, filename)


def test_artifact_path_builds_inside_the_root(tmp_path: Path) -> None:
    path = artifact_path(tmp_path, "job_1", "render", "review.mp4")
    assert path == tmp_path / "job_1" / "render" / "review.mp4"
