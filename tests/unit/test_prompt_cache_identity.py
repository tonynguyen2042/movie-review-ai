"""A prompt's cache identity must follow its content, not just its version (T112).

The constitution requires that a prompt change invalidates the AI artifacts
that depend on it. That is only true if the cache key moves when the prompt's
*text* moves.

Before this, every cache key used ``f"{prompt.name}:{prompt.version}"``. Editing
``scene_analysis_v1.md`` without bumping the frontmatter version left the key
unchanged, so one run could serve scenes analysed under the old text from cache
while newer scenes were analysed under the new text -- a corpus built from two
prompts, with nothing in the output recording it.

These tests pin the fix at both levels: the property on ``Prompt``, and the key a
vision stage actually computes.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.cache.manager import CacheManager
from movie_review.config.prompts import Prompt, load_prompt
from movie_review.vision.analysis import STAGE_VERSION

FRONTMATTER = "---\nname: {name}\nversion: {version}\n---\n\n{body}\n"


def _write_prompt(directory: Path, name: str, version: str, body: str) -> Path:
    """Write one prompt file and return its path."""
    path = directory / f"{name}_{version}.md"
    path.write_text(FRONTMATTER.format(name=name, version=version, body=body), encoding="utf-8")
    return path


def _load__prompt_cache_identity(directory: Path, name: str, version: str, body: str) -> Prompt:
    _write_prompt(directory, name, version, body)
    return load_prompt(name, version, base=directory)


# ---------------------------------------------------------------------------
# The property itself
# ---------------------------------------------------------------------------


def test_cache_version_names_the_prompt_and_its_version() -> None:
    prompt = load_prompt("scene_analysis", "v1")

    assert prompt.cache_version.startswith("scene_analysis:v1:")


def test_cache_version_is_stable_for_identical_content(tmp_path: Path) -> None:
    first = _load__prompt_cache_identity(tmp_path, "p", "v1", "same body")
    second = load_prompt("p", "v1", base=tmp_path)

    assert first.cache_version == second.cache_version


def test_cache_version_changes_when_only_the_body_changes(tmp_path: Path) -> None:
    """The whole point: same name, same version, different text."""
    before = _load__prompt_cache_identity(tmp_path, "p", "v1", "original wording")
    after = _load__prompt_cache_identity(tmp_path, "p", "v1", "revised wording")

    assert before.version == after.version
    assert before.cache_version != after.cache_version


def test_cache_version_changes_when_the_version_is_bumped(tmp_path: Path) -> None:
    v1 = _load__prompt_cache_identity(tmp_path, "p", "v1", "body")
    v2 = _load__prompt_cache_identity(tmp_path, "p", "v2", "body")

    assert v1.cache_version != v2.cache_version


def test_cache_version_carries_enough_of_the_digest_to_be_collision_resistant(
    tmp_path: Path,
) -> None:
    prompt = _load__prompt_cache_identity(tmp_path, "p", "v1", "body")

    # 16 hex characters, not the bare version and not the full 64: short enough
    # to stay readable in a log line, long enough that two prompts cannot share
    # it by accident. `rsplit` because the name and version are colon-separated
    # too, so the digest is the last field rather than the third.
    digest = prompt.cache_version.rsplit(":", 1)[1]
    assert len(digest) == 16
    assert digest == prompt.sha256[:16]


# ---------------------------------------------------------------------------
# The key a vision run actually computes
# ---------------------------------------------------------------------------


@pytest.fixture
def vision_ctx(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _vision_key(prompt: Prompt) -> str:
    """The key shape `run_visual_analysis` builds, with the prompt as input."""
    return cache_key(
        CacheSpec(
            stage="vision",
            stage_version=STAGE_VERSION,
            input_hash="a" * 64,
            model_id="Qwen3-VL",
            prompt_version=prompt.cache_version,
        )
    )


def test_editing_a_prompt_body_invalidates_the_vision_key(tmp_path: Path) -> None:
    before = _vision_key(_load__prompt_cache_identity(tmp_path, "p", "v1", "original wording"))
    after = _vision_key(_load__prompt_cache_identity(tmp_path, "p", "v1", "revised wording"))

    assert before != after


def test_the_cache_manager_reports_the_edit_as_a_miss(tmp_path: Path) -> None:
    """End to end: a stored analysis is unreachable once the prompt is edited."""
    cache = CacheManager(tmp_path / "cache")
    original = _load__prompt_cache_identity(tmp_path, "p", "v1", "original wording")
    key = _vision_key(original)
    cache.store_json(key, {"analysis": {"scene_id": "scene_000001"}})

    assert cache.lookup_json(key) is not None

    edited = _load__prompt_cache_identity(tmp_path, "p", "v1", "revised wording")

    assert cache.lookup_json(_vision_key(edited)) is None


def test_unchanged_prompt_still_hits(tmp_path: Path) -> None:
    """The fix must not turn every run into a cache miss."""
    cache = CacheManager(tmp_path / "cache")
    first = _load__prompt_cache_identity(tmp_path, "p", "v1", "stable wording")
    key = _vision_key(first)
    cache.store_json(key, {"analysis": {"scene_id": "scene_000001"}})

    second = load_prompt("p", "v1", base=tmp_path)

    assert _vision_key(second) == key
    assert cache.lookup_json(key) is not None


# ---------------------------------------------------------------------------
# The shipped prompts are named by the same property
# ---------------------------------------------------------------------------


def test_shipped_prompt_cache_version_is_the_new_form() -> None:
    prompt = load_prompt("scene_analysis", "v1")

    assert prompt.cache_version == f"scene_analysis:v1:{prompt.sha256[:16]}"
