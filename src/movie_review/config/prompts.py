"""Versioned prompt loading and rendering (T024, plan section 7).

Prompts live under ``config/prompts/`` as Markdown with YAML frontmatter
(``name`` + ``version``). Every load returns the exact version used so jobs
can record it; prompt changes invalidate dependent AI artifacts.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template

import yaml

PROMPTS_DIRNAME = "prompts"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


class PromptError(Exception):
    """Prompt loading or rendering failed in a classified way."""


@dataclass(frozen=True)
class Prompt:
    """One versioned prompt template."""

    name: str
    version: str
    template: str
    sha256: str


def prompts_dir(base: str | Path | None = None) -> Path:
    """Prompts directory: explicit base, else ``<repo>/config/prompts``."""
    if base is not None:
        return Path(base)
    return Path(__file__).resolve().parents[3] / "config" / PROMPTS_DIRNAME


def _parse(path: Path) -> Prompt:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise PromptError(f"Prompt {path} lacks YAML frontmatter")
    try:
        header = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise PromptError(f"Prompt {path} has invalid frontmatter: {exc}") from exc
    if not isinstance(header, dict) or "name" not in header or "version" not in header:
        raise PromptError(f"Prompt {path} frontmatter needs name and version")
    return Prompt(
        name=str(header["name"]),
        version=str(header["version"]),
        template=match.group(2),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def list_versions(name: str, base: str | Path | None = None) -> list[str]:
    """All available versions of a prompt, sorted ascending."""
    directory = prompts_dir(base)
    versions = []
    for path in sorted(directory.glob(f"{name}_*.md")):
        prompt = _parse(path)
        if prompt.name != name:
            raise PromptError(f"Prompt file {path} has mismatched name {prompt.name!r}")
        versions.append(prompt.version)
    return sorted(versions)


def load_prompt(name: str, version: str | None = None, base: str | Path | None = None) -> Prompt:
    """Load a prompt; ``version`` None selects the latest available version."""
    directory = prompts_dir(base)
    if version is None:
        available = list_versions(name, directory)
        if not available:
            raise PromptError(f"Unknown prompt: {name}")
        version = available[-1]
    path = directory / f"{name}_{_safe_version(version)}.md"
    if not path.is_file():
        raise PromptError(f"Unknown prompt version: {name} {version}")
    prompt = _parse(path)
    if prompt.version != version:
        raise PromptError(f"Prompt file {path} declares version {prompt.version!r}")
    return prompt


def _safe_version(version: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", version):
        raise PromptError(f"Unsafe prompt version: {version!r}")
    return version


def render(prompt: Prompt, **variables: str) -> str:
    """Substitute ``$variables``; missing values raise :class:`PromptError`."""
    try:
        return Template(prompt.template).substitute(variables)
    except KeyError as exc:
        raise PromptError(f"Missing prompt variable for {prompt.name}: {exc}") from exc
    except ValueError as exc:
        raise PromptError(f"Bad prompt placeholder in {prompt.name}: {exc}") from exc
