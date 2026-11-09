"""Keep docs/GETTING-STARTED.md honest.

The guide is the first thing a new user reads, and it drifts silently: the
CLI grew commands the guide never mentioned, and the guide went on claiming
`resume` and `retry` were unimplemented after they shipped.

These tests execute the documented behavior rather than diffing prose, so a
stale claim fails here instead of misleading someone at the terminal.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "GETTING-STARTED.md"

#: The environment every CLI subprocess runs in. The child's stdout encoding
#: is pinned to UTF-8 so the parent's decode always matches it, whatever the
#: developer's locale happens to be.
CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

#: Rich draws its help tables with U+2502 when the output encoding can carry
#: it, and falls back to an ASCII pipe when it cannot. Because the child's
#: encoding is pinned to UTF-8, it always draws U+2502 - so an assertion that
#: looks for a table row must not depend on which glyph Rich chose. Python
#: 3.15 makes UTF-8 mode the default, which turns that dependence into a
#: break for everyone.
BOX_SEPARATOR = "\u2502"

COMMANDS = [
    "process",
    "inspect",
    "validate",
    "resume",
    "retry",
    "stages",
    "version",
    "dashboard",
    "analyze",
    "scenes",
    "transcript",
    "story",
    "script",
    "render",
    "thumbnail",
    "benchmark",
]


@pytest.fixture(scope="module")
def guide() -> str:
    assert GUIDE.is_file(), "docs/GETTING-STARTED.md is missing"
    return GUIDE.read_text(encoding="utf-8")


def _normalise(text: str) -> str:
    """Render Rich's box separator as an ASCII pipe.

    The command table is what the assertions below read, and its column
    separator is a glyph Rich picks per output encoding. Normalising it keeps
    the assertions about the command surface rather than about typography.
    """
    return text.replace(BOX_SEPARATOR, "|")


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the CLI and return its result, decoded as UTF-8.

    The decode is pinned rather than left to the locale. Under cp1252 the
    child's UTF-8 output raises `UnicodeDecodeError`, which makes
    `result.stdout` `None` - and every assertion that reads it then fails
    with a `TypeError` about `NoneType` instead of checking the thing it
    claims to check.
    """
    result = subprocess.run(
        ["uv", "run", "movie-review", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
        env=CHILD_ENV,
    )
    result.stdout = _normalise(result.stdout)
    result.stderr = _normalise(result.stderr)
    return result


@pytest.fixture
def fake_movie(tmp_path: Path) -> Path:
    """A file that exists but is not decodable, so ingest fails cleanly."""
    movie = tmp_path / "my-movie.mp4"
    movie.write_bytes(b"\x00\x00\x00\x18ftypmp42not-a-video")
    return movie


@pytest.fixture
def failed_job(tmp_path: Path, fake_movie: Path) -> str:
    """A job that reached FAILED at the ingest stage, with its ID."""
    result = cli("process", str(fake_movie), "--db-path", str(tmp_path / "jobs.db"))
    match = re.search(r"job_id=(\S+)", result.stdout)
    assert match, f"no job_id in output: {result.stdout!r} {result.stderr!r}"
    assert result.returncode != 0, "a non-video should not succeed"
    return match.group(1)


# ---------------------------------------------------------------------------
# The command surface the guide documents
# ---------------------------------------------------------------------------


def test_every_documented_command_exists(guide: str) -> None:
    """Each command the guide names must be real."""
    result = cli("--help")
    assert result.returncode == 0
    for command in COMMANDS:
        assert re.search(rf"\|\s*{command}\s", result.stdout), f"`{command}` is not a command"
        assert f"`{command}`" in guide or f"movie-review {command}" in guide, (
            f"guide never mentions `{command}`"
        )


def test_command_table_is_read_under_either_table_glyph() -> None:
    """The command table must be found however Rich draws its separator.

    Rich uses U+2502 when the output encoding can carry it and an ASCII pipe
    when it cannot. The assertions above look for a table row, so they have to
    hold under both - otherwise the suite passes on a cp1252 developer and
    fails on a UTF-8 one, and fails for everyone once Python 3.15 makes
    UTF-8 mode the default.
    """
    unicode_table = "\n".join(
        [
            "┌──────────────┬──────────────┐",
            "│ process      │ does things  │",
            "│ inspect      │ shows a job  │",
            "└──────────────┴──────────────┘",
        ]
    )
    ascii_table = unicode_table.replace(BOX_SEPARATOR, "|")

    for table in (unicode_table, ascii_table):
        normalised = _normalise(table)
        assert re.search(r"\|\s*process\s", normalised), repr(table)
        assert re.search(r"\|\s*inspect\s", normalised), repr(table)


def test_documented_flags_exist() -> None:
    """Every flag in the guide's option tables must exist on the command."""
    process_help = cli("process", "--help").stdout
    for flag in [
        "--language",
        "--duration",
        "--style",
        "--profile",
        "--spoilers",
        "--output",
        "--db-path",
        "--stage-from",
        "--stage-to",
        "--no-run",
    ]:
        assert flag in process_help, f"process is missing {flag}"

    dashboard_help = cli("dashboard", "--help").stdout
    for flag in ["--host", "--port", "--db-path", "--open-browser", "--no-open-browser"]:
        assert flag in dashboard_help, f"dashboard is missing {flag}"

    assert "--stage" in cli("retry", "--help").stdout


def test_guide_explains_liveness_reporting(guide: str) -> None:
    """A run that looks hung is the complaint that motivated progress output.

    The guide has to say what the `->` and heartbeat lines mean, otherwise
    they are just more noise to decode.
    """
    assert "-> ingest" in guide, "guide shows no live stage-start line"
    assert "still running" in guide, "guide does not explain the heartbeat"
    assert "hung" in guide.lower(), "guide never addresses the 'is it stuck?' question"
    assert "stderr" in guide, "guide does not say where progress goes"


def test_stage_list_matches_the_guide(guide: str) -> None:
    """The stage list must match the real pipeline exactly, in order."""
    result = cli("stages")
    assert result.returncode == 0
    actual = [line.strip().split(":")[0] for line in result.stdout.splitlines() if ":" in line]

    block = re.search(r"## 6\. Pipeline stages.*?```text\n(.*?)```", guide, re.S)
    assert block, "guide no longer has a stages code block"
    documented = [line.strip().split(":")[0] for line in block.group(1).splitlines() if ":" in line]

    assert actual == documented, f"guide lists {documented}, pipeline runs {actual}"


def test_stage_names_used_in_examples_are_real(guide: str) -> None:
    """A `--stage-from` example naming a nonexistent stage would not run."""
    real = {line.strip().split(":")[0] for line in cli("stages").stdout.splitlines() if ":" in line}
    used = set(re.findall(r"--stage-from ([a-z-]+)", guide)) | set(
        re.findall(r"--stage-to ([a-z-]+)", guide)
    )
    # 'nope' is the deliberate invalid name in the rejection example.
    assert used - {"nope"} <= real, f"guide names unknown stages: {used - {'nope'} - real}"


# ---------------------------------------------------------------------------
# Behavior the guide asserts
# ---------------------------------------------------------------------------


def test_version_matches_the_guide() -> None:
    assert cli("version").stdout.strip() == "0.1.0"


def test_process_reports_the_job_id_and_fails_loudly(fake_movie: Path, tmp_path: Path) -> None:
    """The guide shows `job_id=... status=CREATED` and a non-zero exit.

    The job ID goes to stdout because it is the machine-readable handle you
    pass to every other command. Progress and logs go to stderr, and progress
    is suppressed when stderr is not a terminal -- which is the case here, so
    this subprocess sees JSON logs but no `->` lines.
    """
    result = cli("process", str(fake_movie), "--db-path", str(tmp_path / "jobs.db"))
    assert re.search(r"job_id=\S+ status=CREATED", result.stdout), result.stdout
    assert result.returncode != 0
    # the failure is recorded even when progress lines are suppressed
    assert '"to_status": "FAILED"' in result.stderr, result.stderr[-300:]


def test_process_keeps_stdout_machine_readable(fake_movie: Path, tmp_path: Path) -> None:
    """stdout must stay parseable: only the job ID, no progress noise.

    Progress on stdout would break `JOB=$(movie-review process m.mp4 | ...)`.
    """
    result = cli("process", str(fake_movie), "--db-path", str(tmp_path / "jobs.db"))
    for line in result.stdout.splitlines():
        assert not line.strip().startswith("->"), f"progress leaked to stdout: {line!r}"
        assert "still running" not in line, f"heartbeat leaked to stdout: {line!r}"


def test_progress_is_suppressed_when_not_a_terminal(fake_movie: Path, tmp_path: Path) -> None:
    """A redirected log should not gain a heartbeat every 10 seconds."""
    result = cli("process", str(fake_movie), "--db-path", str(tmp_path / "jobs.db"))
    assert "still running" not in result.stderr, "heartbeat emitted into a pipe"


def test_progress_appears_when_a_terminal_is_present(fake_movie: Path, tmp_path: Path) -> None:
    """Force the interactive path the guide documents."""
    script = (
        "import importlib, sqlite3, sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, 'src')\n"
        "cliapp = importlib.import_module('movie_review.cli.app')\n"
        "cliapp._progress_enabled = lambda: True\n"
        "from movie_review.pipeline.orchestrator import (\n"
        "    PipelineContext, run_stage, StageResult)\n"
        "from movie_review.cache.manager import CacheManager\n"
        "from movie_review.config.settings import load_settings\n"
        "from movie_review.jobs.manager import JobManager\n"
        "conn = sqlite3.connect(':memory:')\n"
        "conn.row_factory = sqlite3.Row\n"
        "ctx = PipelineContext(\n"
        "    job_id='j', movie_path=Path('m.mp4'), jobs_dir=Path('.'),\n"
        "    cache=CacheManager(Path('.')), manager=JobManager(conn),\n"
        "    settings=load_settings(), conn=conn)\n"
        "rep = cliapp._ProgressReporter(enabled=True)\n"
        "run_stage('transcript', lambda c: None, ctx, on_progress=rep)\n"
        "rep.close()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
        env=CHILD_ENV,
    )
    combined = result.stdout + result.stderr
    assert "-> transcript" in combined, combined[-200:]
    assert "transcript: OK" in combined, combined[-200:]


def test_no_run_skips_the_pipeline(fake_movie: Path, tmp_path: Path) -> None:
    """`--no-run` is documented to exit 0 and point at `resume`."""
    result = cli("process", str(fake_movie), "--db-path", str(tmp_path / "jobs.db"), "--no-run")
    assert result.returncode == 0
    assert "Pipeline execution skipped" in result.stdout
    assert "'resume' to start" in result.stdout


def test_inspect_reports_the_failure(failed_job: str, tmp_path: Path) -> None:
    """The guide's sample record must match the real shape."""
    result = cli("inspect", failed_job, "--db-path", str(tmp_path / "jobs.db"))
    assert result.returncode == 0
    record = json.loads(result.stdout)
    assert record["status"] == "FAILED"
    assert record["failed_stage"] == "ingest"
    assert record["error"], "a failed job must record why"
    assert "retry_count" in record


def test_validate_passes_on_a_cleanly_failed_job(failed_job: str, tmp_path: Path) -> None:
    """valid=True means the record is well-formed, not that the run succeeded."""
    result = cli("validate", failed_job, "--db-path", str(tmp_path / "jobs.db"))
    assert result.returncode == 0
    assert "valid=True" in result.stdout


@pytest.mark.parametrize("command", ["inspect", "validate", "resume", "retry"])
def test_unknown_job_is_a_usage_error(command: str, tmp_path: Path) -> None:
    """All four commands report an unknown ID the same way, exit 2."""
    result = cli(command, "job_nope", "--db-path", str(tmp_path / "jobs.db"))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert "Unknown job" in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Claims about limitations must stay true until they are fixed
# ---------------------------------------------------------------------------


def test_failed_is_terminal(failed_job: str, tmp_path: Path) -> None:
    """The guide tells users to resubmit because FAILED cannot be left.

    If this ever starts passing, the guide's limitation section is stale and
    should be rewritten rather than left claiming a fixed limitation.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from movie_review.domain import JobStatus
    from movie_review.jobs.state_machine import allowed

    assert not allowed(JobStatus.FAILED), (
        "FAILED is now escapable; update the 'What does not work yet' section"
    )


def test_retry_cannot_rescue_a_failed_job(failed_job: str, tmp_path: Path) -> None:
    """Retry is documented as exhausting against a FAILED job, not working."""
    result = cli("retry", failed_job, "--db-path", str(tmp_path / "jobs.db"))
    assert result.returncode != 0
    assert "Retry exhausted" in result.stdout + result.stderr


def test_bad_stage_name_is_rejected_before_a_job_exists(fake_movie: Path, tmp_path: Path) -> None:
    """The guide promises exit 2 and no stray job record."""
    db = tmp_path / "jobs.db"
    result = cli("process", str(fake_movie), "--db-path", str(db), "--stage-from", "nope")
    assert result.returncode == 2
    assert "Traceback" not in result.stdout + result.stderr
    assert not db.exists(), "a rejected run must not leave a jobs database"


# ---------------------------------------------------------------------------
# Stale content that previously shipped in the guide
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stale",
    [
        "474 passed",
        "Pipeline stages arrive in later phases",
        "job is queued",
        "resume is not implemented yet",
        "Not implemented (T085)",
        "not yet merged into `master`",
    ],
)
def test_guide_has_no_stale_claims(guide: str, stale: str) -> None:
    """Text from the pre-T084 guide must not come back."""
    assert stale not in guide


def test_guide_links_only_to_files_that_exist(guide: str) -> None:
    """A broken link in the first-read document is a real papercut."""
    for rel in set(re.findall(r"\]\(\.\./([^)]+)\)", guide)):
        assert (ROOT / rel).exists(), f"guide links to missing {rel}"


def test_guide_documents_the_remote_profile(guide: str) -> None:
    """config/config.yaml ships a working `remote` profile; the guide must cover it."""
    assert "MOVIE_REVIEW_MODELS__PROFILE" in guide
    assert "api_key_env" in guide, "remote credentials need explaining"


def test_guide_documents_publishing(guide: str) -> None:
    """The publish command previews before uploading; the guide has to say so."""
    assert "movie-review publish" in guide
    assert "--confirm" in guide, "the opt-in flag is the safety property"
    assert "Preview only" in guide or "preview" in guide.lower()


def test_guide_explains_where_publishing_credentials_come_from(guide: str) -> None:
    """Credentials come from the environment; a token in a tracked file is a leak."""
    assert "MOVIE_REVIEW_FACEBOOK_PAGE_ID" in guide
    assert "MOVIE_REVIEW_FACEBOOK_TOKEN" in guide
    assert "MOVIE_REVIEW_TIKTOK_TOKEN" in guide


def test_guide_states_the_metadata_evidence_constraint(guide: str) -> None:
    """The generated title may not assert plot facts the narration does not state."""
    assert "INSUFFICIENT_EVIDENCE" in guide
    assert "narration" in guide


def test_guide_records_the_platform_differences(guide: str) -> None:
    """Facebook cannot take a per-video privacy value; TikTok needs app review.

    Both are things a user discovers only by failing, so the guide names them.
    """
    assert "TikTok" in guide
    assert "developer review" in guide
    assert "Reels" in guide, "the unsupported Facebook surfaces should be named"


def test_guide_makes_no_copyright_safety_claim(guide: str) -> None:
    """AGENTS.md: never claim a fixed duration or percentage is legally safe."""
    lowered = guide.lower()
    assert "legally safe" in lowered
    assert "jurisdiction" in lowered
