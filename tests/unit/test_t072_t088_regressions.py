"""Regression tests for defects found reviewing the T072-T088 modules.

Each test pins a specific bug so it cannot come back.

Also pins the CLI stage-name validation added while rewriting
docs/GETTING-STARTED.md, since that guide documents the exit code.
"""

import tempfile
from pathlib import Path
from typing import cast

import pytest

from movie_review.artifacts.integrity import (
    ArtifactRecord,
    IntegrityReport,
    scan_job_integrity,
    verify_or_raise,
)
from movie_review.artifacts.manager import sha256_file, write_json
from movie_review.benchmark.memory import benchmark_memory
from movie_review.domain import Job, JobStatus
from movie_review.eval.coverage_eval import evaluate_coverage
from movie_review.eval.hallucination import evaluate_hallucinations
from movie_review.eval.regression import run_regression
from movie_review.jobs.manager import JobManager
from movie_review.jobs.recovery import _RESUME_STAGE, RecoveryMappingError

MAJOR = {"type": "PLOT_FACT"}


# ---------------------------------------------------------------------------
# F3: path traversal in the integrity scanner (most serious)
# ---------------------------------------------------------------------------


def test_integrity_scanner_blocks_path_traversal() -> None:
    """A record naming '../..' must not hash a file outside the job root.

    Regression: raw ``root / stage / filename`` joins let a corrupted manifest
    point the scanner at arbitrary files. ``artifact_path`` rejects this.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        jobs = root / "jobs"
        (jobs / "job_ok").mkdir(parents=True)

        secret = root / "secret.txt"
        secret.write_text("TOP SECRET")

        report = scan_job_integrity(
            jobs,
            "job_ok",
            [ArtifactRecord(relative_path="../../secret.txt", expected_hash=sha256_file(secret))],
        )
        assert report.ok == 0
        assert report.unsafe == ["../../secret.txt"]
        assert report.passed is False


def test_integrity_scanner_blocks_traversal_in_filename() -> None:
    """Traversal via the filename segment is rejected too."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        jobs = root / "jobs"
        (jobs / "job_ok").mkdir(parents=True)
        (root / "secret.txt").write_text("x")

        report = scan_job_integrity(
            jobs,
            "job_ok",
            [ArtifactRecord(relative_path="qc/../secret.txt", expected_hash="0" * 64)],
        )
        assert report.unsafe == ["qc/../secret.txt"]
        assert report.passed is False


def test_verify_or_raise_rejects_unsafe_paths() -> None:
    """The raising variant refuses unsafe records."""
    with tempfile.TemporaryDirectory() as tmp:
        jobs = Path(tmp) / "jobs"
        (jobs / "job_ok").mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="Unsafe artifact paths"):
            verify_or_raise(
                jobs,
                "job_ok",
                [ArtifactRecord(relative_path="../../x", expected_hash="0" * 64)],
            )


def test_integrity_scanner_still_accepts_valid_records() -> None:
    """The guard must not break the happy path."""
    with tempfile.TemporaryDirectory() as tmp:
        jobs = Path(tmp) / "jobs"
        job_dir = jobs / "job_ok"
        (job_dir / "qc").mkdir(parents=True)
        # write_json returns the content hash
        expected = write_json(job_dir / "qc" / "report.json", {"a": 1})

        report = scan_job_integrity(
            jobs,
            "job_ok",
            [ArtifactRecord(relative_path="qc/report.json", expected_hash=expected)],
        )
        assert report.ok == 1
        assert report.passed is True
        assert report.unsafe == []


def test_integrity_scanner_detects_corruption() -> None:
    """A mismatched hash is reported as corrupt, not as ok."""
    with tempfile.TemporaryDirectory() as tmp:
        jobs = Path(tmp) / "jobs"
        job_dir = jobs / "job_ok"
        (job_dir / "qc").mkdir(parents=True)
        write_json(job_dir / "qc" / "report.json", {"a": 1})

        report = scan_job_integrity(
            jobs,
            "job_ok",
            [ArtifactRecord(relative_path="qc/report.json", expected_hash="0" * 64)],
        )
        assert report.corrupt == ["qc/report.json"]
        assert report.passed is False


def test_integrity_report_passed_requires_all_three_clean() -> None:
    """passed is false when any of missing/corrupt/unsafe is non-empty."""
    assert IntegrityReport(job_id="j", ok=1).passed is True
    assert IntegrityReport(job_id="j", missing=["a"]).passed is False
    assert IntegrityReport(job_id="j", corrupt=["a"]).passed is False
    assert IntegrityReport(job_id="j", unsafe=["a"]).passed is False


# ---------------------------------------------------------------------------
# F1/F2: vacuous passes on empty claim sets
# ---------------------------------------------------------------------------


def test_hallucination_gate_reports_zero_rate_when_nothing_measured() -> None:
    """With no major claims the rate is 0.0 and the gate is not penalised.

    Intent preserved from the original T081 tests: an opinion-only review has
    nothing to hallucinate about. The measured value stays honest at 0.0.
    """
    report = evaluate_hallucinations([])
    assert report.major_total == 0
    assert report.rate == 0.0
    assert report.passed is True


def test_hallucination_gate_still_passes_on_real_clean_claims() -> None:
    report = evaluate_hallucinations([{**MAJOR, "verdict": "SUPPORTED"}])
    assert report.passed is True


def test_coverage_does_not_fabricate_100_percent_on_empty_claims() -> None:
    """Regression: coverage returned 100.0 when there was nothing to measure.

    The gate verdict is unchanged (still not penalised), but the reported
    number must not claim a perfect measurement that never happened.
    """
    report = evaluate_coverage([], [])
    assert report.major_total == 0
    assert report.coverage == 0.0
    assert report.passed is True


def test_coverage_ignores_non_major_claims() -> None:
    """Only major claims count toward the coverage denominator."""
    report = evaluate_coverage([{"type": "OPINION", "evidence": []}], ["ev1"])
    assert report.major_total == 0
    assert report.coverage == 0.0
    assert report.passed is True


def test_coverage_passes_when_all_major_claims_covered() -> None:
    report = evaluate_coverage([{**MAJOR, "evidence": ["ev1"]}], ["ev1"])
    assert report.coverage == 100.0
    assert report.passed is True


def test_regression_gate_passes_on_opinion_only_review() -> None:
    """Preserved intent: opinion-only reviews are not blocked by the gate."""
    report = run_regression(["e1"], ["e1"], [{"claim_id": "o", "type": "OPINION"}], [])
    assert report.passed is True
    assert report.failures == []


def test_regression_gate_passes_on_healthy_golden_set() -> None:
    """A real, well-supported claim set still passes."""
    claims = [
        {"claim_id": "c1", "type": "PLOT_FACT", "evidence": ["ev1"], "verdict": "SUPPORTED"},
        {"claim_id": "c2", "type": "PLOT_FACT", "evidence": ["ev1"], "verdict": "SUPPORTED"},
    ]
    report = run_regression(["e1"], ["e1"], claims, ["ev1"])
    assert report.passed is True
    assert report.failures == []


def test_eval_gates_still_fail_real_problems() -> None:
    """The fixes did not weaken genuine detection."""
    bad = [{"claim_id": "c1", "type": "PLOT_FACT", "evidence": [], "verdict": "CONTRADICTED"}]
    assert evaluate_hallucinations(bad).passed is False
    assert evaluate_coverage(bad, ["ev1"]).passed is False


# ---------------------------------------------------------------------------
# CLI error surface consistency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["inspect", "validate", "resume", "retry"])
def test_cli_reports_unknown_job_without_a_traceback(tmp_path, capsys, command: str) -> None:
    """Every job command must report an unknown ID as a usage error.

    Regression: validate and resume called the job loader directly, so a bad
    job ID produced a raw JobNotFoundError traceback and exit code 1, while
    inspect and retry exited 2 with a clean message.
    """
    from typer.testing import CliRunner

    from movie_review.cli.app import app

    db = tmp_path / "jobs.db"
    result = CliRunner().invoke(app, [command, "job_does_not_exist", "--db-path", str(db)])
    output = result.output
    assert "Traceback (most recent call last)" not in output
    assert "Unknown job" in output
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Stage-name validation happens before a job is recorded
# ---------------------------------------------------------------------------


def test_bad_stage_name_is_a_usage_error_not_a_traceback(tmp_path) -> None:
    """A bad --stage-from must fail as a usage error, exit 2, no traceback.

    Regression: the name was only validated inside run_pipeline, so the job
    record had already been created by the time it raised, leaving a stray
    CREATED job and a raw ValueError traceback for a simple typo.
    """
    from typer.testing import CliRunner

    from movie_review.cli.app import app

    movie = tmp_path / "m.mp4"
    movie.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    result = CliRunner().invoke(
        app,
        [
            "process",
            str(movie),
            "--db-path",
            str(tmp_path / "jobs.db"),
            "--stage-from",
            "nope",
        ],
    )
    assert result.exit_code == 2
    assert "Traceback" not in result.output
    assert "nope" in result.output
    assert "tts-reconcile" in result.output, "should list the valid stage names"


def test_bad_stage_name_creates_no_job_record(tmp_path) -> None:
    """The validation must run before the job is persisted."""
    from typer.testing import CliRunner

    from movie_review.cli.app import app

    movie = tmp_path / "m.mp4"
    movie.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    db = tmp_path / "jobs.db"

    result = CliRunner().invoke(
        app, ["process", str(movie), "--db-path", str(db), "--stage-to", "bogus"]
    )
    assert result.exit_code == 2
    assert not db.exists(), "a rejected run must not leave a jobs database behind"


@pytest.mark.parametrize("flag", ["--stage-from", "--stage-to"])
def test_valid_stage_names_are_accepted(tmp_path, flag: str) -> None:
    """The real stage names must not be rejected by the new validation."""
    from typer.testing import CliRunner

    from movie_review.cli.app import app

    movie = tmp_path / "m.mp4"
    movie.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    result = CliRunner().invoke(
        app,
        [
            "process",
            str(movie),
            "--db-path",
            str(tmp_path / "jobs.db"),
            flag,
            "quality",
            "--no-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Pipeline execution skipped" in result.output


def test_measured_coverage_is_never_above_100() -> None:
    """Sanity: the reported percentage stays a real measurement."""
    claims = [{**MAJOR, "evidence": ["ev1"]} for _ in range(3)]
    report = evaluate_coverage(claims, ["ev1"])
    assert 0.0 <= report.coverage <= 100.0
    assert report.coverage == 100.0


# ---------------------------------------------------------------------------
# Threshold duplication: one source of truth
# ---------------------------------------------------------------------------


def test_eval_coverage_threshold_matches_runtime_gate() -> None:
    """The offline evaluator and the runtime gate must agree.

    Regression: both hardcoded 90.0, so tightening one left the other stale
    and the golden evaluation could pass while the live gate failed.
    """
    from movie_review.eval.coverage_eval import MIN_EVIDENCE_COVERAGE
    from movie_review.quality.gates import GATE_THRESHOLDS

    assert MIN_EVIDENCE_COVERAGE == GATE_THRESHOLDS["evidence_coverage"]


def test_regression_gate_uses_the_shared_coverage_threshold() -> None:
    """The aggregate golden gate follows the same shared threshold."""
    from movie_review.quality.gates import GATE_THRESHOLDS

    target = GATE_THRESHOLDS["evidence_coverage"]

    # 9 of 10 covered = 90.0% -> passes at 90, fails if the target rises
    claims = [{**MAJOR, "evidence": ["ev1"]} for _ in range(9)]
    claims.append({"claim_id": "bare", **MAJOR, "evidence": []})
    report = run_regression(["e1"], ["e1"], claims, ["ev1"])
    assert report.coverage == target
    assert report.passed is True


# ---------------------------------------------------------------------------
# F4: wrong exception type for a missing resume mapping
# ---------------------------------------------------------------------------


class _StubJob:
    def __init__(self, status: JobStatus) -> None:
        self.status = status
        self.failed_stage = None
        self.error = None


class _StubManager(JobManager):
    """A JobManager that answers `get` from a fixed status.

    It is a real JobManager with only `get` replaced, because
    `recovery_plan` takes a JobManager and only ever calls `get`.
    """

    def __init__(self, status: JobStatus) -> None:  # noqa: D107 - no super().__init__
        self._status = status

    def get(self, job_id: str) -> Job:
        return cast(Job, _StubJob(self._status))


def test_recovery_mapping_gap_raises_its_own_error(monkeypatch) -> None:
    """An unmapped status must raise RecoveryMappingError.

    Regression: it raised JobNotFoundError, so callers reported an internal
    gap as a missing job. The mapping is currently complete, so a key is
    removed here to exercise the failure path.
    """
    from movie_review.jobs import recovery as recovery_mod

    monkeypatch.delitem(recovery_mod._RESUME_STAGE, JobStatus.RENDERED)
    with pytest.raises(RecoveryMappingError, match="No resume mapping"):
        recovery_mod.recovery_plan(_StubManager(JobStatus.RENDERED), "job_x")


def test_recovery_covers_every_job_status() -> None:
    """Every non-FAILED status has a resume mapping, so the gap is unreachable."""
    for status in JobStatus:
        if status is JobStatus.FAILED:
            continue
        assert status in _RESUME_STAGE, f"{status} has no resume mapping"


def test_recovery_mapping_error_is_not_job_not_found() -> None:
    """Callers must be able to tell the two apart."""
    from movie_review.jobs.state_machine import JobNotFoundError

    assert not issubclass(RecoveryMappingError, JobNotFoundError)


# ---------------------------------------------------------------------------
# F5: memory benchmark side effects
# ---------------------------------------------------------------------------


def test_benchmark_memory_does_not_stop_caller_tracing() -> None:
    """Regression: the benchmark always called tracemalloc.stop()."""
    import tracemalloc

    tracemalloc.start()
    try:
        benchmark_memory("op", lambda: [0] * 1000)
        assert tracemalloc.is_tracing() is True, "caller's tracing was disabled"
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()


def test_benchmark_memory_works_without_tracing() -> None:
    import tracemalloc

    assert tracemalloc.is_tracing() is False
    result = benchmark_memory("op", lambda: [0] * 1000)
    assert result.peak_bytes > 0
    assert result.peak_mb > 0
    # and it cleaned up after itself
    assert tracemalloc.is_tracing() is False


def test_benchmark_memory_reports_peak_not_current() -> None:
    """peak must be >= current; guards the swapped/duplicated read."""
    result = benchmark_memory("op", lambda: [0] * 100_000)
    assert result.peak_bytes >= result.current_bytes
