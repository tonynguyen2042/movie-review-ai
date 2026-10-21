"""The prompt registry has to name the prompts that exist, and be honoured.

T152. `config/default.yaml` declared versions for `character_analysis`,
`story_analysis`, `review_planner`, `fact_checker` and `visual_planner` —
none of which were ever written. The eight prompt files that did exist were
not listed at all.

Separately, `settings.prompts.versions` was read by nothing: the loader
always took the newest file. The registry was decorative, so a prompt version
could never be pinned and a rollback to an earlier prompt was impossible.
"""

from __future__ import annotations

from pathlib import Path

from movie_review.config.prompts import (
    list_versions,
    load_prompt,
    pinned_version,
    prompts_dir,
)
from movie_review.config.settings import load_settings


def _prompt_files() -> set[str]:
    """The names of the prompt files that exist."""
    return {path.stem.rsplit("_", 1)[0] for path in prompts_dir().glob("*.md")}


def test_the_registry_names_only_prompts_that_exist() -> None:
    """The registry named five prompts that were never written."""
    versions = load_settings().prompts.versions
    missing = set(versions) - _prompt_files()
    assert not missing, f"the registry names prompts that do not exist: {sorted(missing)}"


def test_every_prompt_file_is_in_the_registry() -> None:
    """The five prompts that did exist were not listed at all."""
    versions = load_settings().prompts.versions
    unlisted = _prompt_files() - set(versions)
    assert not unlisted, f"prompts that exist but are not registered: {sorted(unlisted)}"


def test_a_pinned_version_is_loaded() -> None:
    """The registry was decorative; a version could never be pinned."""
    name = "scene_analysis"
    pinned = pinned_version(name)
    assert pinned is not None, f"{name} is not pinned"
    prompt = load_prompt(name)
    assert prompt.version == pinned


def test_an_explicit_version_wins_over_the_registry() -> None:
    """A caller that asks for a version gets it."""
    name = "scene_analysis"
    available = list_versions(name, prompts_dir())
    assert available
    chosen = available[0]
    prompt = load_prompt(name, chosen)
    assert prompt.version == chosen


def test_a_prompt_the_registry_does_not_name_uses_the_newest(tmp_path: Path) -> None:
    """An unregistered prompt falls back to its newest version."""
    # A copy of the prompt directory with a second version of one prompt.
    base = tmp_path / "prompts"
    base.mkdir()
    for version in ("v1", "v2"):
        (base / f"demo_{version}.md").write_text(
            f"---\nname: demo\nversion: {version}\n---\nbody {version}\n",
            encoding="utf-8",
        )
    prompt = load_prompt("demo", base=base)
    assert prompt.version == "v2"
    assert "body v2" in prompt.template


def test_the_registry_names_the_prompts_the_pipeline_uses() -> None:
    """Every prompt the stages load has to be a real, registered prompt."""
    used = (
        "scene_analysis",
        "event_extraction",
        "story_arc",
        "theme",
        "twist",
        "script_writer",
        "translate",
        "publishing_metadata",
    )
    versions = load_settings().prompts.versions
    for name in used:
        assert name in versions, f"{name} is not registered"
        assert load_prompt(name).version == versions[name]
