"""The repository must have a CI that runs the checks, and a coverage gate.

T160. There was no `.github/workflows/` at the repository root, so nothing
ran the test suite on a push or a pull request. `coverage` and `pytest-cov`
were not installed and `pyproject.toml` had no coverage configuration, so the
coverage level was unknown.

The three pipeline blockers — a render stage that raised `KeyError` on every
run, a quality gate that could not fail, and a manifest timed with a
hard-coded number — all reached master because nothing executed the stage
closures.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _config() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        loaded: dict[str, Any] = tomllib.load(handle)
        return loaded


def _workflow() -> dict[str, Any]:
    assert WORKFLOW.is_file(), "there is no CI workflow"
    loaded: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return loaded


def test_the_workflow_exists() -> None:
    """Nothing ran the suite on a push or a pull request."""
    assert WORKFLOW.is_file()


def test_the_workflow_runs_on_push_and_on_pull_requests() -> None:
    workflow = _workflow()
    # PyYAML reads the `on:` key as the boolean True.
    raw: dict[Any, Any] = workflow
    triggers = raw.get("on")
    if triggers is None:
        triggers = raw.get(True)
    assert triggers is not None
    assert "push" in triggers
    assert "pull_request" in triggers


def test_the_workflow_runs_the_four_required_checks() -> None:
    """AGENTS.md STEP 11 names pytest, ruff, ruff format and mypy."""
    workflow = _workflow()
    commands = " ".join(str(step.get("run", "")) for step in workflow["jobs"]["checks"]["steps"])
    assert "ruff check" in commands
    assert "ruff format --check" in commands
    assert "mypy" in commands
    assert "pytest" in commands


def test_the_workflow_measures_the_coverage() -> None:
    """The coverage level was unknown."""
    workflow = _workflow()
    commands = " ".join(str(step.get("run", "")) for step in workflow["jobs"]["checks"]["steps"])
    assert "--cov=movie_review" in commands


def test_the_workflow_runs_on_the_target_platform() -> None:
    """The target is Apple Silicon, so macos has to be in the matrix."""
    workflow = _workflow()
    platforms = workflow["jobs"]["checks"]["strategy"]["matrix"]["os"]
    assert any("macos" in platform for platform in platforms)
    assert any("ubuntu" in platform for platform in platforms)


def test_the_coverage_tool_is_a_declared_dependency() -> None:
    """A CI that installs the tool by hand is a CI that breaks."""
    dev = _config()["project"]["optional-dependencies"]["dev"]
    assert any("pytest-cov" in requirement for requirement in dev)


def test_the_coverage_is_configured() -> None:
    coverage = _config()["tool"]["coverage"]
    assert coverage["run"]["source"] == ["src/movie_review"]
    assert coverage["run"]["branch"] is True


def test_the_coverage_gate_is_set_and_reachable() -> None:
    """The gate has to be a number the suite can actually clear."""
    threshold = _config()["tool"]["coverage"]["report"]["fail_under"]
    assert isinstance(threshold, (int, float))
    assert 0 < threshold < 100
    # The suite measured 89.57% with branch coverage; the floor has to be
    # below that, or the gate can never be met.
    assert threshold < 89.57


def test_the_lock_file_knows_the_coverage_tool() -> None:
    """`uv sync` fails against a lock file that does not have the dependency."""
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert "pytest-cov" in lock
