"""T002 acceptance: typed settings, YAML defaults, environment overrides."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from movie_review.config.settings import ModelSpec, load_settings
from movie_review.remote import http

REPO = Path(__file__).resolve().parents[2]
DEFAULT_YAML = REPO / "config" / "default.yaml"
MODELS_YAML = REPO / "config" / "models.yaml"


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in list(__import__("os").environ):
        if var == "MOVIE_REVIEW_CONFIG" or var.startswith("MOVIE_REVIEW_"):
            monkeypatch.delenv(var, raising=False)


def test_defaults_load_from_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    settings = load_settings()
    assert settings.models.profile == "balanced"
    assert settings.models.reasoning.model == "Qwen3.5-27B"
    assert settings.pipeline.review.target_duration_minutes == 20
    assert settings.pipeline.review.target_wpm == 150
    assert settings.privacy.cloud_ai is False
    assert settings.prompts.versions["script_writer"] == "v1"


def test_env_overrides_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("MOVIE_REVIEW_PIPELINE__REVIEW__TARGET_WPM", "180")
    settings = load_settings()
    assert settings.pipeline.review.target_wpm == 180
    # Untouched values still come from YAML.
    assert settings.pipeline.review.target_duration_minutes == 20


def test_explicit_config_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clean_env(monkeypatch)
    custom = tmp_path / "custom.yaml"
    custom.write_text(
        "models:\n  profile: balanced\n"
        "pipeline:\n  review:\n    target_duration_minutes: 10\n    target_wpm: 150\n"
        "prompts:\n  versions:\n    script_writer: v9\n",
        encoding="utf-8",
    )
    models = tmp_path / "models.yaml"
    models.write_text(MODELS_YAML.read_text(encoding="utf-8"), encoding="utf-8")
    settings = load_settings(config_path=custom, models_path=models)
    assert settings.pipeline.review.target_duration_minutes == 10
    assert settings.prompts.versions["script_writer"] == "v9"


def test_config_path_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clean_env(monkeypatch)
    custom = tmp_path / "custom.yaml"
    custom.write_text(
        "models:\n  profile: fast\nprompts:\n  versions:\n    script_writer: v1\n",
        encoding="utf-8",
    )
    models = tmp_path / "models.yaml"
    models.write_text(MODELS_YAML.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("MOVIE_REVIEW_CONFIG", str(custom))
    # models.yaml resolves next to the selected config file.
    settings = load_settings()
    assert settings.models.profile == "fast"
    assert settings.models.reasoning.model == "Qwen3.5-9B"


def test_profile_switch_changes_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model identities are configurable: switching profile changes resolution."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("MOVIE_REVIEW_MODELS__PROFILE", "fast")
    settings = load_settings()
    assert settings.models.reasoning.model == "Qwen3.5-9B"
    assert settings.models.tts.model == "Qwen3-TTS-0.6B"


def test_unknown_profile_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("MOVIE_REVIEW_MODELS__PROFILE", "nope")
    with pytest.raises(ValueError, match="Unknown model profile"):
        load_settings()


def test_missing_config_file_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clean_env(monkeypatch)
    with pytest.raises(FileNotFoundError):
        load_settings(config_path=tmp_path / "absent.yaml")


def test_invalid_values_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("MOVIE_REVIEW_SOURCE_VIDEO__MAX_SOURCE_RATIO", "1.5")
    with pytest.raises(ValidationError):
        load_settings()


# --- the transport retry schedule ----------------------------------------


def test_a_model_spec_defaults_to_the_transport_schedule() -> None:
    spec = ModelSpec(model="m", backend="openai_compatible", base_url="http://gpu:8000/v1")

    assert spec.retry == http.DEFAULT_RETRY


def test_a_model_spec_carries_its_own_retry_schedule() -> None:
    spec = ModelSpec(
        model="m",
        backend="openai_compatible",
        base_url="http://gpu:8000/v1",
        attempts=4,
        backoff_seconds=5.0,
        max_backoff_seconds=30.0,
    )

    assert spec.retry == http.TransportRetry(
        attempts=4, backoff_seconds=5.0, max_backoff_seconds=30.0
    )


def test_an_attempt_budget_below_one_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelSpec(
            model="m",
            backend="openai_compatible",
            base_url="http://gpu:8000/v1",
            attempts=0,
        )


def test_the_remote_profile_gives_vision_three_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped profile must outlast a vLLM engine reloading, not a blip."""
    _clean_env(monkeypatch)
    settings = load_settings(profile="remote")

    vision = settings.models.vision.retry
    assert vision.attempts == 4
    assert vision.backoff_seconds == 5.0
    # Three retries: 5 s, 10 s and 20 s, roughly the reload window.
    assert vision.max_backoff_seconds == 30.0
