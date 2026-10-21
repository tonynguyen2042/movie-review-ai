"""The repository structure README section 7 promises has to be real.

T170. The `scripts/` directory held two task-workflow helpers and none of
the four scripts the README lists: `benchmark_models.py`,
`benchmark_pipeline.py`, `validate_movie.py` and `cleanup_cache.py`.

The measurement and validation code already existed in `movie_review`, so
the scripts are thin wrappers around it -- the structure is what was
missing, and duplicating the logic would have been the wrong fix.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from movie_review.cache.manager import CacheManager

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

#: The four scripts README section 7 lists.
SECTION_7_SCRIPTS = (
    "benchmark_models.py",
    "benchmark_pipeline.py",
    "validate_movie.py",
    "cleanup_cache.py",
)


def _load(name: str) -> Any:
    """Load a script as a module, the way a caller would run it."""
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(f"_script_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_named_script_exists() -> None:
    """The directory held two task helpers and none of the four."""
    for name in SECTION_7_SCRIPTS:
        assert (SCRIPTS / name).is_file(), f"{name} is missing"


@pytest.mark.parametrize("name", SECTION_7_SCRIPTS)
def test_every_script_answers_its_help(name: str) -> None:
    """A script that cannot be run is a file, not a tool."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / name), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage:" in result.stdout


def test_the_cache_can_be_pruned(tmp_path: Path) -> None:
    """The cache grew without bound; nothing ever removed an entry."""
    cache = CacheManager(tmp_path / "cache")
    cache.store("first", b"payload")
    cache.store("second", b"payload")

    removed = cache.prune()

    assert removed == ["first", "second"]
    assert cache.lookup("first") is None
    assert cache.lookup("second") is None


def test_the_prune_keeps_the_recent_entries(tmp_path: Path) -> None:
    """A run in progress must not be pruned out from under itself."""
    cache = CacheManager(tmp_path / "cache")
    cache.store("old", b"payload")
    cache.store("new", b"payload")

    # The old entry is a minute old; the new one is a second old.
    import os

    meta = tmp_path / "cache" / "old.meta.json"
    old_time = time.time() - 3600
    os.utime(meta, (old_time, old_time))

    removed = cache.prune(older_than_seconds=600)

    assert removed == ["old"]
    assert cache.lookup("new") is not None


def test_the_prune_of_an_empty_cache_is_harmless(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache")
    assert cache.prune() == []


def test_the_age_is_read_in_the_units_a_person_would_use() -> None:
    """``7d`` is what a person writes; seconds is what the code wants."""
    module = _load("cleanup_cache.py")
    assert module._seconds("30m") == 1800
    assert module._seconds("2h") == 7200
    assert module._seconds("7d") == 604800
    assert module._seconds("90") == 90


def test_an_unreadable_age_is_reported() -> None:
    module = _load("cleanup_cache.py")
    with pytest.raises(ValueError, match="Cannot read"):
        module._seconds("soon")


def test_the_cleanup_reports_without_removing(tmp_path: Path, monkeypatch) -> None:
    """A dry run has to promise what a real run would do."""
    module = _load("cleanup_cache.py")
    cache = CacheManager(tmp_path / "cache")
    cache.store("entry", b"payload")

    removed = module._prune_cache(tmp_path / "cache", None, True)

    assert removed == ["entry"]
    assert cache.lookup("entry") is not None, "the dry run removed something"


def test_the_cleanup_removes_what_it_reports(tmp_path: Path) -> None:
    module = _load("cleanup_cache.py")
    cache = CacheManager(tmp_path / "cache")
    cache.store("entry", b"payload")

    removed = module._prune_cache(tmp_path / "cache", None, False)

    assert removed == ["entry"]
    assert cache.lookup("entry") is None


def test_the_frames_are_dropped_but_the_manifest_stays(tmp_path: Path) -> None:
    """The manifest is the record of what was sampled; the images are the bulk."""
    module = _load("cleanup_cache.py")
    job_dir = tmp_path / "jobs" / "job_1"
    frames = job_dir / "frames" / "scene_000001"
    frames.mkdir(parents=True)
    (frames / "frame.jpg").write_bytes(b"\x00")
    (job_dir / "frames" / "frames.json").write_text("{}", encoding="utf-8")

    removed = module._drop_frames(tmp_path / "jobs", False)

    assert removed
    assert not (frames / "frame.jpg").exists()
    assert (job_dir / "frames" / "frames.json").is_file()
