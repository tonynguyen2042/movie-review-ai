"""The pause before a stage that needs a model.

One machine cannot hold every model at once: whisper, the vision model, the
reasoner and the TTS model compete for the same memory, so a run that swaps
them has to stop long enough for the operator to load the next one. The
pipeline asks once per stage, not once per call -- a vision run makes one
call per scene, and a prompt before each of them would be unusable.

What the operator needs to see is the model, the URL and the port: that is
what they load on the machine serving the request.
"""

from __future__ import annotations

import os

import pytest

from movie_review.config.settings import AppSettings, load_settings
from movie_review.pipeline.model_gate import (
    MODEL_STAGES,
    ModelCall,
    ModelStageDeclined,
    model_call_for,
    render_model_call,
)


def _settings__model_gate(monkeypatch: pytest.MonkeyPatch, profile: str = "remote") -> AppSettings:
    """The configured profile, with nothing in the environment overriding it."""
    for var in list(os.environ):
        if var.startswith("MOVIE_REVIEW_"):
            monkeypatch.delenv(var, raising=False)
    return load_settings(profile=profile)


def _call__model_gate(monkeypatch: pytest.MonkeyPatch, stage: str) -> ModelCall:
    settings = _settings__model_gate(monkeypatch)
    call = model_call_for(stage, settings, source_language="en", target_language="en")
    assert call is not None, f"{stage} should need a model"
    return call


@pytest.mark.parametrize("stage", sorted(MODEL_STAGES))
def test_every_model_stage_names_its_slot(monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    """The table and the settings have to agree about which slot runs."""
    settings = _settings__model_gate(monkeypatch)
    call = model_call_for(stage, settings, source_language="en", target_language="fr")
    assert call is not None
    assert call.stage == stage
    assert call.slot == MODEL_STAGES[stage]


@pytest.mark.parametrize(
    "stage",
    [
        "ingest",
        "scenes",
        "characters",
        "locations",
        "story",
        "render-manifest",
        "render",
        "quality",
    ],
)
def test_a_stage_without_a_model_is_not_asked(monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    """Scene detection and the render do no inference; a pause would be noise."""
    settings = _settings__model_gate(monkeypatch)
    assert model_call_for(stage, settings, source_language="en", target_language="en") is None


def test_the_remote_profile_reports_the_url_and_the_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The three lines the operator needs to load the right model."""
    call = _call__model_gate(monkeypatch, "vision")
    assert call.model == "Qwen3-VL"
    assert call.backend == "openai_compatible"
    assert call.base_url == "http://192.168.1.144:8000/v1"
    assert call.port == 8000


def test_the_tts_slot_reports_its_own_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """A slot is independent: the narration model is not the reasoner's."""
    call = _call__model_gate(monkeypatch, "tts-chunks")
    assert call.slot == "tts"
    assert call.model == "Qwen3-TTS-12Hz-1.7B"
    assert call.port == 8000


def test_a_local_checkpoint_reports_no_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing to swap on a server that does not exist."""
    settings = _settings__model_gate(monkeypatch, profile="balanced")
    call = model_call_for("vision", settings, source_language="en", target_language="en")
    assert call is not None
    assert call.base_url is None
    assert call.port is None
    assert "local" in render_model_call(call)


def test_translation_is_skipped_when_nothing_is_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same language in and out means no model call, so no pause either."""
    settings = _settings__model_gate(monkeypatch)
    assert (
        model_call_for("review-translate", settings, source_language="en", target_language="en")
        is None
    )
    asked = model_call_for("review-translate", settings, source_language="en", target_language="fr")
    assert asked is not None
    assert asked.slot == "translation"
    assert asked.model == "Qwen3.5-9B"


def test_translation_falls_back_to_the_reasoner(monkeypatch: pytest.MonkeyPatch) -> None:
    """A profile without a translation slot runs translation on reasoning."""
    settings = _settings__model_gate(monkeypatch, profile="balanced")
    call = model_call_for("review-translate", settings, source_language="en", target_language="fr")
    assert call is not None
    assert call.slot == "translation"
    assert call.model == settings.models.reasoning.model


def test_verify_asks_only_when_the_critic_is_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The critic is optional; a pause for a model that will not run is a lie."""
    settings = _settings__model_gate(monkeypatch)
    assert not settings.models.critic.enabled
    assert model_call_for("verify", settings, source_language="en", target_language="en") is None

    enabled = settings.model_copy(
        update={
            "models": settings.models.model_copy(
                update={"critic": settings.models.critic.model_copy(update={"enabled": True})}
            )
        }
    )
    call = model_call_for("verify", enabled, source_language="en", target_language="en")
    assert call is not None
    assert call.slot == "critic"


def test_the_block_names_the_model_the_url_and_the_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The output is the instruction: what to load, and where."""
    block = render_model_call(_call__model_gate(monkeypatch, "vision"))
    assert "vision needs a model" in block
    assert "Qwen3-VL" in block
    assert "http://192.168.1.144:8000/v1" in block
    assert "port : 8000" in block
    assert "slot : vision" in block


def test_an_implicit_port_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """A URL without a port still connects somewhere; say where."""
    spec = _settings__model_gate(monkeypatch).models.vision.model_copy(
        update={"base_url": "http://gpu-box.local/v1"}
    )
    settings = _settings__model_gate(monkeypatch)
    settings = settings.model_copy(
        update={"models": settings.models.model_copy(update={"vision": spec})}
    )
    call = model_call_for("vision", settings, source_language="en", target_language="en")
    assert call is not None
    assert call.port == 80


def test_a_declined_stage_says_which_one_it_was() -> None:
    """The caller prints this, so it has to name the stage."""
    exc = ModelStageDeclined("vision")
    assert exc.stage == "vision"
    assert "vision" in str(exc)
