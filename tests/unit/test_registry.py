"""T034 acceptance: deduped registration and source lookup."""

import sqlite3
from pathlib import Path

from movie_review.domain import Evidence, EvidenceType, Job
from movie_review.knowledge.registry import find_by_source, find_by_type, register_evidence
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _db__registry(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(bootstrap(tmp_path / "e.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    return conn


def _evidence(
    source: str, confidence: float, type: EvidenceType = EvidenceType.DIALOGUE
) -> Evidence:
    return Evidence(id=f"{source}-{confidence}", type=type, source_id=source, confidence=confidence)


def test_register_new(tmp_path: Path) -> None:
    conn = _db__registry(tmp_path)
    assert register_evidence(conn, "job_1", _evidence("seg_1", 0.9)) is True
    assert len(repo.list_evidence(conn, "job_1")) == 1
    conn.close()


def test_register_dedupes_lower_confidence(tmp_path: Path) -> None:
    conn = _db__registry(tmp_path)
    register_evidence(conn, "job_1", _evidence("seg_1", 0.9))
    assert register_evidence(conn, "job_1", _evidence("seg_1", 0.5)) is False
    [kept] = repo.list_evidence(conn, "job_1")
    assert kept.confidence == 0.9
    conn.close()


def test_register_upgrades_confidence(tmp_path: Path) -> None:
    conn = _db__registry(tmp_path)
    register_evidence(conn, "job_1", _evidence("seg_1", 0.5))
    assert register_evidence(conn, "job_1", _evidence("seg_1", 0.9)) is True
    [kept] = repo.list_evidence(conn, "job_1")
    assert kept.confidence == 0.9
    conn.close()


def test_same_source_different_types_coexist(tmp_path: Path) -> None:
    conn = _db__registry(tmp_path)
    register_evidence(conn, "job_1", _evidence("s1", 0.9, EvidenceType.DIALOGUE))
    register_evidence(conn, "job_1", _evidence("s1", 0.8, EvidenceType.SCENE))
    assert len(find_by_source(conn, "job_1", "s1")) == 2
    assert find_by_source(conn, "job_1", "missing") == []
    assert len(find_by_type(conn, "job_1", EvidenceType.SCENE)) == 1
    conn.close()
