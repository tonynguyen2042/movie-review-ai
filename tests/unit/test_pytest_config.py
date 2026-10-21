"""The pytest configuration has to be strict and selectable.

T162. There were no registered markers, so a developer could not select the
tests that need ffmpeg or the ones that need MLX — the only way to express
it was a local `skipif` in each file, which is a silent exclusion rather
than a selection. There was no `--strict-markers`, so a typo in a marker
name passed unnoticed, no `--strict-config`, no `xfail_strict`, and no
per-test timeout: a hanging test blocked the run indefinitely.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _pytest_config() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        loaded: dict[str, Any] = tomllib.load(handle)
        return loaded


def test_the_markers_are_registered() -> None:
    """A developer has to be able to select a subset."""
    markers = _pytest_config()["tool"]["pytest"]["ini_options"]["markers"]
    names = {line.split(":")[0].strip() for line in markers}
    assert {"ffmpeg", "mlx", "slow", "network"} <= names


def test_the_run_is_strict() -> None:
    """A typo in a marker name, or a bad ini option, must fail the run."""
    addopts = _pytest_config()["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--strict-markers" in addopts
    assert "--strict-config" in addopts


def test_an_xfail_that_starts_passing_is_a_failure() -> None:
    config = _pytest_config()["tool"]["pytest"]["ini_options"]
    assert config["xfail_strict"] is True


def test_a_hanging_test_is_bounded() -> None:
    config = _pytest_config()["tool"]["pytest"]["ini_options"]
    assert isinstance(config["timeout"], int)
    assert config["timeout"] > 0


def test_the_timeout_plugin_is_a_declared_dependency() -> None:
    dev = _pytest_config()["project"]["optional-dependencies"]["dev"]
    assert any("pytest-timeout" in requirement for requirement in dev)


def test_the_ffmpeg_tests_are_marked() -> None:
    """The local skip becomes a selection."""
    source = (ROOT / "tests" / "unit" / "test_detection.py").read_text(encoding="utf-8")
    assert "@pytest.mark.ffmpeg" in source
    assert "NEEDS_FFMPEG" not in source


def test_a_marker_selection_really_selects() -> None:
    """The marker has to mean something to pytest."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-m", "not ffmpeg"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "deselected" in result.stdout
