"""T007 acceptance: deterministic paths, hashes, atomic writes, integrity."""

from pathlib import Path

import pytest

from movie_review.artifacts import manager as artifacts


def test_paths_deterministic(tmp_path: Path) -> None:
    first = artifacts.artifact_path(tmp_path, "job_1", "scenes", "scenes.json")
    second = artifacts.artifact_path(tmp_path, "job_1", "scenes", "scenes.json")
    assert first == second == tmp_path / "job_1" / "scenes" / "scenes.json"
    assert artifacts.manifest_path(tmp_path, "job_1") == tmp_path / "job_1" / "manifest.json"


@pytest.mark.parametrize(
    "job_id,stage,filename",
    [
        ("../escape", "scenes", "a.json"),
        ("job_1", "..", "a.json"),
        ("job_1", "scenes", "../../evil"),
        ("", "scenes", "a.json"),
        ("job_1", "scenes", "a/b.json"),
        ("job_1", "scenes", ".hidden"),
    ],
)
def test_unsafe_segments_rejected(tmp_path: Path, job_id: str, stage: str, filename: str) -> None:
    with pytest.raises(artifacts.UnsafePathError):
        artifacts.artifact_path(tmp_path, job_id, stage, filename)


@pytest.mark.parametrize("job_id", ["../escape", "", ".."])
def test_unsafe_manifest_job_rejected(tmp_path: Path, job_id: str) -> None:
    with pytest.raises(artifacts.UnsafePathError):
        artifacts.manifest_path(tmp_path, job_id)


def test_write_read_round_trip(tmp_path: Path) -> None:
    target = artifacts.artifact_path(tmp_path, "job_1", "scenes", "s.json")
    digest = artifacts.write_bytes(target, b"\x00\x01")
    assert artifacts.sha256_file(target) == digest
    assert artifacts.read_bytes(target, digest) == b"\x00\x01"
    assert artifacts.sha256_bytes(b"\x00\x01") == digest


def test_no_tmp_files_left(tmp_path: Path) -> None:
    target = artifacts.artifact_path(tmp_path, "job_1", "tts", "a.wav")
    artifacts.write_bytes(target, b"data")
    leftovers = list((tmp_path / "job_1" / "tts").glob("*.tmp-*"))
    assert leftovers == []


def test_tamper_detected(tmp_path: Path) -> None:
    target = artifacts.artifact_path(tmp_path, "job_1", "review", "script.json")
    digest = artifacts.write_json(target, {"a": 1})
    assert artifacts.read_json(target, digest) == {"a": 1}
    target.write_bytes(b"tampered")
    with pytest.raises(artifacts.ArtifactIntegrityError):
        artifacts.verify(target, digest)
    with pytest.raises(artifacts.ArtifactIntegrityError):
        artifacts.read_json(target, digest)


def test_text_round_trip(tmp_path: Path) -> None:
    target = artifacts.artifact_path(tmp_path, "job_1", "review", "script.md")
    digest = artifacts.write_text(target, "# Review\n")
    assert artifacts.read_text(target, digest) == "# Review\n"


def test_missing_file_verify_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        artifacts.verify(tmp_path / "absent.bin", "0" * 64)
