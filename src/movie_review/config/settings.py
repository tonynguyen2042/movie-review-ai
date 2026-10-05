"""Typed application settings with YAML defaults and environment overrides.

Precedence (highest first): init kwargs > ``MOVIE_REVIEW_*`` environment
variables > YAML files > code fallbacks.

Nested overrides join segments with ``__`` after the single-underscore prefix,
e.g. ``MOVIE_REVIEW_PIPELINE__REVIEW__TARGET_WPM=180``.

Model identities and prompt versions have no code fallbacks: they must come
from ``models.yaml`` / ``default.yaml`` so no model name, path, duration,
WPM, threshold, memory budget, or prompt version is hard-coded.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, Field, PositiveFloat, PositiveInt
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

CONFIG_ENV_VAR = "MOVIE_REVIEW_CONFIG"
ENV_PREFIX = "MOVIE_REVIEW_"

RatioFloat = Annotated[float, Field(ge=0.0, le=1.0)]


def repo_root() -> Path:
    """Repository root inferred from this file's location."""
    return Path(__file__).resolve().parents[3]


def default_config_path() -> Path:
    """Default ``config/default.yaml`` path (overridable via ``MOVIE_REVIEW_CONFIG``)."""
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        return Path(override)
    return repo_root() / "config" / "default.yaml"


def default_models_path(config_path: Path) -> Path:
    """Model catalog path: ``models.yaml`` next to the active config file."""
    return config_path.parent / "models.yaml"


def read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML mapping file or raise a clear error."""
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file must contain a mapping: {path}")
    return data


class RuntimeSettings(BaseModel):
    """Model runtime backend selection."""

    backend: str = "mlx"
    device: str = "gpu"


class ModelSpec(BaseModel):
    """A single model entry; identities come from ``models.yaml``."""

    model: str
    precision: str = "4bit"
    enabled: bool = True


class ModelsSettings(BaseModel):
    """Active model set. ``profile`` selects a catalog entry in ``models.yaml``."""

    profile: str = "balanced"
    asr: ModelSpec
    vision: ModelSpec
    reasoning: ModelSpec
    critic: ModelSpec
    tts: ModelSpec


class ReviewSettings(BaseModel):
    """Review length targets (spec FR-014 defaults)."""

    target_duration_minutes: PositiveInt = 20
    target_wpm: PositiveInt = 150


class RenderingSettings(BaseModel):
    """Default output video parameters."""

    width: PositiveInt = 1920
    height: PositiveInt = 1080
    fps: PositiveInt = 30
    preset: str = "veryfast"
    crf: int = Field(ge=0, le=51, default=23)


class SceneDetectionSettings(BaseModel):
    """Scene detector selection; ``threshold`` None means the detector default."""

    detector: str = "adaptive"
    threshold: float | None = None
    min_scene_len: PositiveInt = 15


class VisualSamplingSettings(BaseModel):
    """Duration-adaptive frame sampling buckets (README section 12)."""

    mode: str = "adaptive"
    short_threshold: PositiveFloat = 10.0
    medium_threshold: PositiveFloat = 60.0
    short_frames: PositiveInt = 3
    medium_frames: PositiveInt = 6
    long_frames: PositiveInt = 12


class PipelineSettings(BaseModel):
    """Pipeline stage defaults."""

    scene_detection: SceneDetectionSettings = SceneDetectionSettings()
    visual_sampling: VisualSamplingSettings = VisualSamplingSettings()
    diarization: bool = True
    evidence_required: bool = True
    review: ReviewSettings = ReviewSettings()
    rendering: RenderingSettings = RenderingSettings()


class SourceVideoSettings(BaseModel):
    """Source-footage product controls (NOT a legal guarantee)."""

    max_clip_seconds: PositiveFloat = 8.0
    preferred_clip_seconds: PositiveFloat = 3.0
    max_source_ratio: RatioFloat = 0.35
    max_total_seconds: PositiveFloat = 420.0


class PathsSettings(BaseModel):
    """Configurable data locations."""

    data_dir: str = "data"
    output_dir: str = "data/output"


class PrivacySettings(BaseModel):
    """Local-first defaults: nothing leaves the machine unless enabled."""

    cloud_ai: bool = False
    telemetry: bool = False


class MemorySettings(BaseModel):
    """Unified-memory budget reservation for OS/FFmpeg/Python overhead."""

    reserve_mb: PositiveInt = 8192


class PromptsSettings(BaseModel):
    """Prompt version registry; prompt content lives in ``config/prompts/``."""

    versions: dict[str, str]


class LoggingSettings(BaseModel):
    """Logging output controls."""

    level: str = "INFO"
    json_output: bool = True


class MediaProxySettings(BaseModel):
    """Analysis proxy encoding targets (README section 10)."""

    max_width: PositiveInt = 1280
    max_height: PositiveInt = 720
    preset: str = "veryfast"
    crf: int = Field(ge=0, le=51, default=23)


class MediaSettings(BaseModel):
    """Media tooling binary locations (resolved via PATH when bare names)."""

    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    proxy: MediaProxySettings = MediaProxySettings()


def _profile_from_env() -> str | None:
    """Effective ``models.profile`` override from the environment, if present.

    The profile name selects which ``models.yaml`` subtree loads, so it must be
    resolved inside the YAML source itself (a separate env source merges too
    late). Matching is case-insensitive, mirroring ``case_sensitive=False``.
    """
    for key, value in os.environ.items():
        if key.upper() == f"{ENV_PREFIX}MODELS__PROFILE":
            return value
    return None


class _ProfileYamlSource(YamlConfigSettingsSource):
    """YAML source merging ``default.yaml`` with the active ``models.yaml`` profile.

    ``default.yaml`` carries the ``models.profile`` name (plus optional pins);
    full model identities come from the ``profiles`` catalog in ``models.yaml``.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        config_path: Path,
        models_path: Path,
    ) -> None:
        self._config_path = config_path
        self._models_path = models_path
        super().__init__(settings_cls, yaml_file=config_path)

    def __call__(self) -> dict[str, Any]:
        data = read_yaml(self._config_path)
        models_block = data.get("models", {})
        if not isinstance(models_block, dict):
            raise ValueError(f"'models' must be a mapping: {self._config_path}")
        profile_name = _profile_from_env() or models_block.get("profile", "balanced")
        catalog = read_yaml(self._models_path).get("profiles", {})
        if not isinstance(catalog, dict) or profile_name not in catalog:
            raise ValueError(f"Unknown model profile {profile_name!r} in {self._models_path}")
        profile = catalog[profile_name]
        if not isinstance(profile, dict):
            raise ValueError(f"Profile {profile_name!r} must be a mapping: {self._models_path}")
        data["models"] = {**profile, **models_block}
        return data


class AppSettings(BaseSettings):
    """Root settings object. Prefer :func:`load_settings` over direct use."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX, env_nested_delimiter="__", extra="ignore"
    )

    runtime: RuntimeSettings = RuntimeSettings()
    models: ModelsSettings
    pipeline: PipelineSettings = PipelineSettings()
    source_video: SourceVideoSettings = SourceVideoSettings()
    paths: PathsSettings = PathsSettings()
    privacy: PrivacySettings = PrivacySettings()
    memory: MemorySettings = MemorySettings()
    prompts: PromptsSettings
    logging: LoggingSettings = LoggingSettings()
    media: MediaSettings = MediaSettings()
    style: str = "youtube"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        config_path = default_config_path()
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _ProfileYamlSource(settings_cls, config_path, default_models_path(config_path)),
        )


def load_settings(
    config_path: str | Path | None = None,
    models_path: str | Path | None = None,
) -> AppSettings:
    """Load settings from explicit YAML files with env overrides applied.

    Args:
        config_path: ``default.yaml`` location (default: ``MOVIE_REVIEW_CONFIG``
            env var or ``<repo>/config/default.yaml``).
        models_path: ``models.yaml`` location (default: next to ``config_path``).
    """
    resolved_config = Path(config_path) if config_path else default_config_path()
    resolved_models = Path(models_path) if models_path else default_models_path(resolved_config)

    class _Configured(AppSettings):
        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (
                init_settings,
                env_settings,
                dotenv_settings,
                _ProfileYamlSource(settings_cls, resolved_config, resolved_models),
            )

    return _Configured()  # type: ignore[call-arg]  # sources supply models/prompts
