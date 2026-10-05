"""Review style profiles and loader (T040, README section 26).

Profiles are data: tone, content, hook, and pacing weights that planners and
writers consume. Four initial profiles ship under ``config/styles/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, Field, PositiveInt

Ratio = Annotated[float, Field(ge=0.0, le=1.0)]


class StyleProfile(BaseModel):
    """A named review style with content and pacing controls."""

    name: str = Field(min_length=1)
    language: str = "en"
    target_duration_seconds: PositiveInt = 1200
    target_wpm: PositiveInt = 150
    tone: dict[str, Ratio] = Field(default_factory=dict)
    content: dict[str, Ratio] = Field(default_factory=dict)
    spoilers: str = "full"
    hook: dict[str, Any] = Field(default_factory=dict)
    pacing: dict[str, Any] = Field(default_factory=dict)


class StyleError(Exception):
    """Style profile loading failed in a classified way."""


def styles_dir(base: str | Path | None = None) -> Path:
    """Styles directory: explicit base, else ``<repo>/config/styles``."""
    if base is not None:
        return Path(base)
    return Path(__file__).resolve().parents[3] / "config" / "styles"


def list_styles(base: str | Path | None = None) -> list[str]:
    """Available style names, sorted."""
    return sorted(path.stem for path in styles_dir(base).glob("*.yaml"))


def load_style(name: str, base: str | Path | None = None) -> StyleProfile:
    """Load and validate a style profile by name."""
    path = styles_dir(base) / f"{name}.yaml"
    if not path.is_file():
        raise StyleError(f"Unknown style: {name}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise StyleError(f"Invalid style file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise StyleError(f"Style file must contain a mapping: {path}")
    data.setdefault("name", name)
    try:
        return StyleProfile.model_validate(data)
    except ValueError as exc:
        raise StyleError(f"Invalid style {name}: {exc}") from exc
