"""Cloud AI is opt-in, and the opt-in has to be real.

T150 regression. `privacy.cloud_ai` was declared in the configuration and
read by nothing. The constitution's P7 makes cloud AI opt-in -- no movie
content leaves the machine unless an explicitly configured provider is
enabled -- but a profile that routed a slot at a remote endpoint sent the
movie's dialogue and frames off the machine with no warning.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from movie_review.asr.factory import build_asr_adapter
from movie_review.config.settings import (
    CloudAIDisabledError,
    ModelSpec,
    load_settings,
)
from movie_review.reasoning.factory import build_reasoning_adapter
from movie_review.tts.factory import build_tts_adapter
from movie_review.vision.factory import build_vlm_adapter


def _remote_spec__privacy_gate() -> ModelSpec:
    return ModelSpec(
        model="qwen3.5-27b",
        backend="openai_compatible",
        base_url="http://gpu-box.lan:8000/v1",
    )


def _local_spec() -> ModelSpec:
    return ModelSpec(model="qwen3.5-27b", backend="mlx")


def _remote_profile__privacy_gate() -> dict[str, Any]:
    """The remote profile block the single-file configs below carry."""
    return {
        "asr": {
            "model": "whisper",
            "backend": "openai_compatible",
            "base_url": "http://gpu:9000/v1",
        },
        "vision": {
            "model": "qwen3-vl",
            "backend": "openai_compatible",
            "base_url": "http://gpu:8000/v1",
        },
        "reasoning": {
            "model": "qwen3.5-27b",
            "backend": "openai_compatible",
            "base_url": "http://gpu:8000/v1",
        },
        "critic": {"model": "qwen3.5", "enabled": False},
        "tts": {
            "model": "qwen3-tts",
            "backend": "openai_compatible",
            "base_url": "http://gpu:8000/v1",
        },
    }


def _write_config(tmp_path: Path, cloud_ai: bool) -> Path:
    """One config file: the product controls and the profile catalog together."""
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "models": {"profile": "remote"},
                "prompts": {"versions": {"scene_analysis": "v1"}},
                "privacy": {"cloud_ai": cloud_ai},
                "profiles": {"remote": _remote_profile__privacy_gate()},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_a_remote_spec_is_refused_when_cloud_ai_is_off() -> None:
    """A remote slot must not be used while the flag is off."""
    spec = _remote_spec__privacy_gate().model_copy(update={"cloud_ai": False})
    for build in (build_asr_adapter, build_vlm_adapter, build_reasoning_adapter, build_tts_adapter):
        with pytest.raises(CloudAIDisabledError) as excinfo:
            build(spec)
        message = str(excinfo.value)
        assert "privacy.cloud_ai" in message
        assert "gpu-box.lan" in message


def test_a_remote_spec_is_allowed_when_cloud_ai_is_on() -> None:
    """The opt-in has to work, or the flag is just a lock."""
    spec = _remote_spec__privacy_gate().model_copy(update={"cloud_ai": True})
    assert build_reasoning_adapter(spec) is not None
    assert build_asr_adapter(spec) is not None
    assert build_vlm_adapter(spec) is not None
    assert build_tts_adapter(spec) is not None


def test_a_local_spec_is_never_refused() -> None:
    """A local model sends nothing anywhere."""
    spec = _local_spec().model_copy(update={"cloud_ai": False})
    assert build_reasoning_adapter(spec) is not None


def test_the_flag_travels_on_the_spec(tmp_path: Path) -> None:
    """The configuration records the policy on every slot."""
    settings = load_settings(config_path=_write_config(tmp_path, cloud_ai=False))
    assert settings.privacy.cloud_ai is False
    assert settings.models.vision.cloud_ai is False
    assert settings.models.reasoning.cloud_ai is False
    assert settings.models.tts.cloud_ai is False


def test_the_flag_is_switched_on_by_the_configuration(tmp_path: Path) -> None:
    """`cloud_ai: true` reaches the specs."""
    settings = load_settings(config_path=_write_config(tmp_path, cloud_ai=True))
    assert settings.models.vision.cloud_ai is True
    assert build_vlm_adapter(settings.models.vision) is not None


def test_the_environment_switch_reaches_the_specs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator who exports the variable has to be believed.

    The policy was applied when the YAML source built the profile, and the
    YAML source only sees the YAML. So ``MOVIE_REVIEW_PRIVACY__CLOUD_AI=true``
    set the switch and left every model marked local: the remote models
    were refused with a message naming a switch the operator had already
    turned on.
    """
    path = _write_config(tmp_path, cloud_ai=False)
    monkeypatch.setenv("MOVIE_REVIEW_PRIVACY__CLOUD_AI", "true")

    settings = load_settings(config_path=path)

    assert settings.privacy.cloud_ai is True
    for name in ("asr", "vision", "reasoning", "tts"):
        assert getattr(settings.models, name).cloud_ai is True, name
    assert build_vlm_adapter(settings.models.vision) is not None


def test_the_environment_switch_off_is_believed_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The switch has to be able to close the door as well."""
    path = _write_config(tmp_path, cloud_ai=True)
    monkeypatch.setenv("MOVIE_REVIEW_PRIVACY__CLOUD_AI", "false")

    settings = load_settings(config_path=path)

    assert settings.privacy.cloud_ai is False
    assert settings.models.vision.cloud_ai is False
    with pytest.raises(CloudAIDisabledError):
        build_vlm_adapter(settings.models.vision)
