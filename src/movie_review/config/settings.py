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
from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from movie_review.remote.http import (
    DEFAULT_ATTEMPTS,
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_MAX_BACKOFF_SECONDS,
    TransportRetry,
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


class GenerationSettings(BaseModel):
    """How a model call is sampled (README sections 73 and 74).

    A pinned seed, a fixed temperature and a fixed top_p make a run
    reproducible: the same movie, the same model, the same prompt and the
    same configuration give the same result.
    """

    seed: int = 0
    temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, ge=0.0, le=1.0)


class ModelSpec(BaseModel):
    """A single model entry; identities come from ``models.yaml``.

    ``backend`` selects the runtime that serves the model. ``mlx`` loads
    local weights on Apple Silicon (the historical default). Setting it to
    ``openai_compatible`` targets a remote HTTP server instead, in which case
    ``base_url`` is required.

    ``endpoint_path`` overrides the route for servers whose speech-to-text path
    is not the OpenAI one. whisper.cpp's ``whisper-server``, for example, serves
    ``POST /inference`` and has no ``/audio/transcriptions`` at all, so without
    this the request 404s while the server is healthy. Left unset, each adapter
    keeps its OpenAI-compatible default.

    Secrets are never stored inline: ``api_key_env`` names the environment
    variable that holds the key, so credentials stay out of ``models.yaml``.
    """

    model: str
    precision: str = "4bit"
    enabled: bool = True
    backend: str = "mlx"
    base_url: str | None = None
    endpoint_path: str | None = None
    api_key_env: str | None = None
    timeout_seconds: float = Field(default=120.0, gt=0.0)
    #: How many attempts one HTTP request gets before the adapter hears about
    #: a retryable failure -- a 429, a 5xx, a timeout, a dropped connection.
    #: Total attempts, not retries: 4 means the first try plus three more.
    #: A host that needs a minute to reload a crashed engine wants both more
    #: attempts and a longer wait than the transport defaults.
    attempts: int = Field(default=DEFAULT_ATTEMPTS, ge=1)
    #: Base of the exponential backoff between those attempts, in seconds.
    #: Zero means "retry immediately", not "do not retry".
    backoff_seconds: float = Field(default=DEFAULT_BACKOFF_SECONDS, ge=0.0)
    #: Ceiling for a single backoff sleep; the schedule grows to this and
    #: stops, so a long outage cannot turn into an unbounded wait.
    max_backoff_seconds: float = Field(default=DEFAULT_MAX_BACKOFF_SECONDS, gt=0.0)
    #: Completion-token budget for remote chat models. Left unset, each adapter
    #: applies its own default. Set it when a reply gets cut off -- a truncated
    #: reply is indistinguishable from prose once the closing brace is missing,
    #: and the model needs room for every list it was asked to produce.
    max_tokens: int | None = Field(default=None, gt=0)
    #: How many frames a single vision request may carry. A scene keeps every
    #: frame it sampled, but an endpoint -- a remote one in particular -- may
    #: refuse more images than that in one request. A scene over the cap is
    #: sent with its first and last frames and the rest spaced evenly, so the
    #: request still covers the whole scene.
    max_frames_per_request: int = Field(default=32, ge=1)
    #: Whether this model may be used while ``privacy.cloud_ai`` is off. A
    #: remote model would send movie content off the machine, so the
    #: configuration sets this from the privacy flag. A hand-built spec
    #: defaults to allowed.
    cloud_ai: bool = True
    #: How this model is sampled. The values are part of the cache identity,
    #: so a different temperature is a different answer.
    generation: GenerationSettings = GenerationSettings()

    @property
    def is_remote(self) -> bool:
        """True when this model is served over HTTP by a remote host."""
        return self.backend == "openai_compatible"

    @property
    def retry(self) -> TransportRetry:
        """The transport retry schedule this slot asks for."""
        return TransportRetry(
            attempts=self.attempts,
            backoff_seconds=self.backoff_seconds,
            max_backoff_seconds=self.max_backoff_seconds,
        )

    def resolved_api_key(self) -> str | None:
        """Read the API key from the environment variable named by ``api_key_env``.

        Returns ``None`` when no variable is configured. Raises when the
        variable is named but unset, so a misconfigured deployment fails at
        startup instead of sending unauthenticated requests.
        """
        if not self.api_key_env:
            return None
        value = os.environ.get(self.api_key_env)
        if not value:
            raise ValueError(
                f"api_key_env={self.api_key_env!r} is set but that environment "
                f"variable is empty or missing"
            )
        return value

    @model_validator(mode="after")
    def _validate_endpoint(self) -> ModelSpec:
        """Reject endpoint settings that cannot work, before any request."""
        known = {"mlx", "openai_compatible"}
        if self.backend not in known:
            raise ValueError(
                f"Unknown backend {self.backend!r} for model {self.model!r}; "
                f"expected one of {sorted(known)}"
            )
        if self.is_remote:
            if not self.base_url:
                raise ValueError(
                    f"backend='openai_compatible' requires base_url for model {self.model!r}"
                )
            if not self.base_url.startswith(("http://", "https://")):
                raise ValueError(
                    f"base_url must start with http:// or https://, got {self.base_url!r}"
                )
        if self.endpoint_path is not None:
            if not self.endpoint_path.startswith("/"):
                raise ValueError(
                    f"endpoint_path must start with '/', got {self.endpoint_path!r} "
                    f"for model {self.model!r}"
                )
            if not self.is_remote:
                raise ValueError(
                    f"endpoint_path only applies to backend='openai_compatible', "
                    f"but model {self.model!r} uses {self.backend!r}"
                )
        return self


class CloudAIDisabledError(ValueError):
    """A remote model was requested while cloud AI is switched off.

    The constitution's P7 makes cloud AI opt-in: no movie content leaves
    the machine unless an explicitly configured provider is enabled. The
    flag was declared in the configuration and read by nothing, so a
    profile that routed a slot at a remote endpoint sent the movie's
    dialogue and frames off the machine with no warning.
    """


def generation_config(spec: ModelSpec) -> dict[str, Any]:
    """The sampling settings that affect a model call, for a cache key.

    Two runs with the same prompt but a different temperature are two
    different answers, so the sampling belongs in the cache identity.
    """
    return {
        "seed": spec.generation.seed,
        "temperature": spec.generation.temperature,
        "top_p": spec.generation.top_p,
    }


def require_cloud_ai(spec: ModelSpec, cloud_ai: bool, slot: str) -> None:
    """Refuse to build a remote adapter while cloud AI is switched off.

    Raises:
        CloudAIDisabledError: the slot is remote and the flag is off.
    """
    if spec.is_remote and not cloud_ai:
        raise CloudAIDisabledError(
            f"The {slot} slot routes to {spec.base_url!r}, which would send movie "
            f"content off this machine, but privacy.cloud_ai is false. Set "
            f"privacy.cloud_ai to true to allow it, or use a local profile."
        )


class ModelsSettings(BaseModel):
    """Active model set. ``profile`` selects a catalog entry in ``models.yaml``."""

    profile: str = "balanced"
    asr: ModelSpec
    vision: ModelSpec
    reasoning: ModelSpec
    critic: ModelSpec
    tts: ModelSpec
    #: Dedicated translation model. Optional: a profile that does not declare
    #: one borrows ``reasoning``, which is what it did before the slot existed.
    #: Optional rather than defaulted because there is no sensible checkpoint to
    #: name here, and an invented default would be used by every profile that
    #: forgot to set it.
    translation: ModelSpec | None = None

    @property
    def effective_translation(self) -> ModelSpec:
        """The spec translation should actually run on."""
        return self.translation or self.reasoning


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
    #: Whether the diarization stage runs. The speakers are only needed for
    #: the speaker-to-character linking.
    diarization: bool = True
    review: ReviewSettings = ReviewSettings()
    rendering: RenderingSettings = RenderingSettings()


class SourceVideoSettings(BaseModel):
    """Source-footage product controls (NOT a legal guarantee)."""

    max_clip_seconds: PositiveFloat = 8.0
    preferred_clip_seconds: PositiveFloat = 3.0
    max_source_ratio: RatioFloat = 0.35
    max_total_seconds: PositiveFloat = 420.0


class MusicSettings(BaseModel):
    """The optional music bed (README section 43).

    The music tracks are local assets: nothing is fetched, and nothing about
    the movie leaves the machine because of them. The bed is optional and
    off by default.
    """

    enabled: bool = False
    #: Path to a local audio file, relative to the data directory or
    #: absolute.
    track: str | None = None
    #: How loud the bed is under the narration, before the ducking envelope.
    gain: float = Field(default=1.0, ge=0.0, le=4.0)


class PathsSettings(BaseModel):
    """Configurable data locations."""

    data_dir: str = "data"
    output_dir: str = "data/output"


class PrivacySettings(BaseModel):
    """The local-first privacy switch (P7).

    ``cloud_ai`` gates every remote adapter: a model that would send movie
    content off this machine is refused while it is off.

    There is no telemetry switch because the project sends no telemetry at
    all. A flag promising something that does not exist is worse than no
    flag.
    """

    cloud_ai: bool = False


class InteractionSettings(BaseModel):
    """How the pipeline talks to the operator while it runs.

    ``auto_accept`` decides whether a stage that needs a model starts on its
    own or waits for a human. One machine cannot hold every model at once:
    whisper, the VLM, the reasoner and the TTS model compete for the same
    unified memory, so a run that swaps them has to stop long enough for the
    operator to load the next one. The pause is per stage, not per call -- a
    vision run makes one call per scene, and a prompt before each of them
    would be unusable.

    The default is ``False``: an unattended run has to say that it is
    unattended, rather than the pipeline assuming it.
    """

    auto_accept: bool = False


class PromptsSettings(BaseModel):
    """Prompt version registry; prompt content lives in ``config/prompts/``."""

    versions: dict[str, str]


class LoggingSettings(BaseModel):
    """Logging output controls.

    The output is always JSON: the dashboard and the desktop app both read
    it, and a second format would mean two parsers.
    """

    level: str = "INFO"


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


class _ProfileOverrideSource(PydanticBaseSettingsSource):
    """Highest-priority source carrying an explicit ``models.profile``.

    Settings sources are merged from lowest to highest priority, so this has to
    sit above ``env_settings``: an explicit ``--profile`` must beat
    ``MOVIE_REVIEW_MODELS__PROFILE``. Returning only the one nested key is safe
    because the merge is deep, so the catalog expansion from
    :class:`_ProfileYamlSource` still supplies asr/vision/tts/etc.

    Without this, ``--profile remote`` silently did nothing on any machine that
    had the env var set -- the most likely way for a user to have it set.
    """

    def __init__(self, settings_cls: type[BaseSettings], profile: str) -> None:
        super().__init__(settings_cls)
        self._profile = profile

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        raise NotImplementedError  # not a per-field source

    def __call__(self) -> dict[str, Any]:
        return {"models": {"profile": self._profile}}


def _with_privacy(profile: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Record the privacy policy on every model slot of the profile.

    The constitution's P7 makes cloud AI opt-in: no movie content leaves
    the machine unless an explicitly configured provider is enabled. The
    ``privacy.cloud_ai`` flag was declared in the configuration and read by
    nothing, so a profile that routed a slot at a remote endpoint sent the
    movie's dialogue and frames off the machine with no warning.

    The policy travels on the model spec rather than as a separate argument
    to the adapter factories: the spec is the configured model, and a
    factory that only has the spec still knows the rule it has to obey.
    """
    privacy = data.get("privacy")
    cloud_ai = bool(privacy.get("cloud_ai", False)) if isinstance(privacy, dict) else False
    updated: dict[str, Any] = {}
    for name, spec in profile.items():
        if isinstance(spec, dict):
            updated[name] = {**spec, "cloud_ai": cloud_ai}
        else:
            updated[name] = spec
    return updated


class _ProfileYamlSource(YamlConfigSettingsSource):
    """YAML source merging ``default.yaml`` with the active ``models.yaml`` profile.

    ``default.yaml`` carries the ``models.profile`` name (plus optional pins);
    full model identities come from the ``profiles`` catalog in ``models.yaml``.

    Precedence is ``profile_override`` (a CLI flag), then
    ``MOVIE_REVIEW_MODELS__PROFILE``, then ``default.yaml``, then ``balanced``.
    An explicit flag has to beat the environment: a user who exported the
    variable once should still be able to override it per run.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        config_path: Path,
        models_path: Path,
        profile_override: str | None = None,
    ) -> None:
        self._config_path = config_path
        self._models_path = models_path
        self._profile_override = profile_override
        super().__init__(settings_cls, yaml_file=config_path)

    def __call__(self) -> dict[str, Any]:
        data = read_yaml(self._config_path)
        models_block = data.get("models", {})
        if not isinstance(models_block, dict):
            raise ValueError(f"'models' must be a mapping: {self._config_path}")
        profile_name = (
            self._profile_override or _profile_from_env() or models_block.get("profile", "balanced")
        )
        catalog = read_yaml(self._models_path).get("profiles", {})
        if not isinstance(catalog, dict) or profile_name not in catalog:
            raise ValueError(f"Unknown model profile {profile_name!r} in {self._models_path}")
        profile = catalog[profile_name]
        if not isinstance(profile, dict):
            raise ValueError(f"Profile {profile_name!r} must be a mapping: {self._models_path}")
        data["models"] = {**_with_privacy(profile, data), **models_block}
        return data


class AppSettings(BaseSettings):
    """Root settings object. Prefer :func:`load_settings` over direct use."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX, env_nested_delimiter="__", extra="ignore"
    )

    models: ModelsSettings
    pipeline: PipelineSettings = PipelineSettings()
    source_video: SourceVideoSettings = SourceVideoSettings()
    paths: PathsSettings = PathsSettings()
    music: MusicSettings = MusicSettings()
    privacy: PrivacySettings = PrivacySettings()
    interaction: InteractionSettings = InteractionSettings()
    prompts: PromptsSettings
    logging: LoggingSettings = LoggingSettings()
    media: MediaSettings = MediaSettings()

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


def _override_sources(
    settings_cls: type[BaseSettings], profile: str | None
) -> tuple[PydanticBaseSettingsSource, ...]:
    """Highest-priority sources for explicit caller overrides."""
    if profile is None:
        return ()
    return (_ProfileOverrideSource(settings_cls, profile),)


def available_profiles(
    config_path: str | Path | None = None,
    models_path: str | Path | None = None,
) -> list[str]:
    """Names present in the ``models.yaml`` profile catalog.

    Lets the CLI validate ``--profile`` and list the real choices in ``--help``
    instead of hardcoding a list that silently omits ``remote``.
    """
    resolved_config = Path(config_path) if config_path else default_config_path()
    resolved_models = Path(models_path) if models_path else default_models_path(resolved_config)
    catalog = read_yaml(resolved_models).get("profiles", {})
    if not isinstance(catalog, dict):
        raise ValueError(f"'profiles' must be a mapping: {resolved_models}")
    return list(catalog)


def load_settings(
    config_path: str | Path | None = None,
    models_path: str | Path | None = None,
    *,
    profile: str | None = None,
    generation: GenerationSettings | None = None,
) -> AppSettings:
    """Load settings from explicit YAML files with env overrides applied.

    Args:
        config_path: ``default.yaml`` location (default: ``MOVIE_REVIEW_CONFIG``
            env var or ``<repo>/config/default.yaml``).
        models_path: ``models.yaml`` location (default: next to ``config_path``).
        profile: explicit profile name, overriding the environment and
            ``default.yaml``. Raises :class:`ValueError` if the name is not in
            the ``models.yaml`` catalog.
        generation: pins the sampling of every model slot, which is what
            ``--deterministic`` uses. The values are part of the cache
            identity, so a pinned run and an ordinary one do not share
            answers.
    """
    resolved_config = Path(config_path) if config_path else default_config_path()
    resolved_models = Path(models_path) if models_path else default_models_path(resolved_config)
    if profile is not None and profile not in available_profiles(resolved_config, resolved_models):
        raise ValueError(
            f"Unknown model profile {profile!r}; available: "
            f"{', '.join(available_profiles(resolved_config, resolved_models))}"
        )

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
                *_override_sources(settings_cls, profile),
                init_settings,
                env_settings,
                dotenv_settings,
                _ProfileYamlSource(
                    settings_cls, resolved_config, resolved_models, profile_override=profile
                ),
            )

    settings: AppSettings = _Configured()  # type: ignore[call-arg]  # sources supply models/prompts
    settings = _with_privacy_policy(settings)
    if generation is not None:
        settings = _with_generation(settings, generation)
    return settings


def _with_privacy_policy(settings: AppSettings) -> AppSettings:
    """Record the privacy policy on every model slot, whatever set it.

    The policy travels on the model spec rather than as a separate argument
    to the adapter factories: the spec is the configured model, and a
    factory that only has the spec still knows the rule it has to obey.

    The YAML source applies the policy when it builds the profile -- but
    the YAML source only sees the YAML. An environment override of
    ``privacy.cloud_ai`` therefore never reached the slots: the switch read
    ``true`` while every model was still marked local, and the remote
    models were refused with a message that named a switch the operator
    had already turned on.
    """
    cloud_ai = settings.privacy.cloud_ai
    models = settings.models
    updated: dict[str, Any] = {}
    for name in ("asr", "vision", "reasoning", "critic", "tts"):
        updated[name] = getattr(models, name).model_copy(update={"cloud_ai": cloud_ai})
    if models.translation is not None:
        updated["translation"] = models.translation.model_copy(update={"cloud_ai": cloud_ai})
    return settings.model_copy(update={"models": models.model_copy(update=updated)})


def _with_generation(settings: AppSettings, generation: GenerationSettings) -> AppSettings:
    """Every model slot sampled the same, reproducible way.

    The sampling is part of the cache identity, so a pinned run and an
    ordinary one do not share answers.
    """
    models = settings.models
    updated: dict[str, Any] = {}
    for name in ("asr", "vision", "reasoning", "critic", "tts"):
        updated[name] = getattr(models, name).model_copy(update={"generation": generation})
    if models.translation is not None:
        updated["translation"] = models.translation.model_copy(update={"generation": generation})
    return settings.model_copy(update={"models": models.model_copy(update=updated)})
