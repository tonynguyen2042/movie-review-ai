"""The pause before a stage that needs a model.

One machine cannot hold every model at once. Whisper, the vision model, the
reasoner and the TTS model compete for the same memory, so a run that uses
all of them has to be told which one it is about to need -- the operator
loads that model, confirms, and the stage starts.

The pause belongs to the pipeline rather than to each stage: the stages
already know which model they build, but ten copies of "ask the operator"
would drift, and a stage that forgot to ask would read as a hang. Here the
answer is one table and one hook, and :func:`run_pipeline` consults it before
every stage it starts.

The confirmation itself is not here. The pipeline receives a callback and
knows nothing about terminals, which keeps the orchestrator usable from
tests, the dashboard and the desktop app -- none of which can answer a
prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from movie_review.config.settings import AppSettings, ModelSpec

#: The model slot each stage needs, for the stages that need one.
#:
#: A stage missing from this table runs without asking: it does no inference,
#: or what it does is not a model call (scene detection, the story assembly,
#: the render). ``verify`` and ``review-translate`` are conditional and are
#: resolved in :func:`model_call_for` rather than here.
MODEL_STAGES: dict[str, str] = {
    "transcript": "asr",
    "vision": "vision",
    "events": "reasoning",
    "arcs": "reasoning",
    "themes": "reasoning",
    "twists": "reasoning",
    "review": "reasoning",
    "review-translate": "translation",
    "tts-chunks": "tts",
}

#: Ports a URL without an explicit port connects to.
_DEFAULT_PORTS = {"http": 80, "https": 443}

_HEADER_WIDTH = 58


class ModelStageDeclined(Exception):
    """The operator stopped the run before a stage that needs a model.

    Not a failure of the stage: nothing ran, the job is exactly where it was,
    and the same stage starts again on ``resume`` once the model is loaded.
    """

    def __init__(self, stage: str) -> None:
        super().__init__(f"Stopped before '{stage}': the model was not confirmed.")
        self.stage = stage


@dataclass(frozen=True)
class ModelCall:
    """The model a stage is about to use, in the terms the operator needs.

    ``base_url`` is ``None`` for a local checkpoint: there is no server to
    switch, only weights to have in memory.
    """

    stage: str
    slot: str
    model: str
    backend: str
    base_url: str | None = None
    port: int | None = None


def _port_of(base_url: str | None) -> int | None:
    """The port a request to ``base_url`` lands on, when it can be known."""
    if not base_url:
        return None
    try:
        split = urlsplit(base_url)
        return split.port or _DEFAULT_PORTS.get(split.scheme)
    except ValueError:
        # A malformed URL is the adapter's problem to report, not this one's.
        return None


def _call(stage: str, slot: str, spec: ModelSpec) -> ModelCall:
    return ModelCall(
        stage=stage,
        slot=slot,
        model=spec.model,
        backend=spec.backend,
        base_url=spec.base_url,
        port=_port_of(spec.base_url),
    )


def model_call_for(
    stage: str,
    settings: AppSettings,
    *,
    source_language: str,
    target_language: str,
) -> ModelCall | None:
    """The model ``stage`` will use, or ``None`` when it uses none.

    Two stages ask conditionally. Translation is skipped entirely when the
    narration is written in the source language, and the critic -- the only
    model the verify stage calls -- is off in most profiles. Asking the
    operator to load a model for work that will not happen is worse than not
    asking at all.
    """
    if stage == "verify":
        critic = settings.models.critic
        return _call(stage, "critic", critic) if critic.enabled else None

    slot = MODEL_STAGES.get(stage)
    if slot is None:
        return None

    if stage == "review-translate":
        if source_language == target_language:
            return None
        # A profile with no translation slot borrows the reasoning model, so
        # the prompt names the model that actually runs.
        return _call(stage, slot, settings.models.effective_translation)

    return _call(stage, slot, getattr(settings.models, slot))


def render_model_call(call: ModelCall) -> str:
    """The block shown before the stage starts.

    The model, the URL and the port are the whole point: they are what the
    operator needs to load on the machine serving the request. The prompt
    text is deliberately absent -- it is the same every run, and printing it
    before each stage would push the three lines that matter off the screen.
    """
    lines = [
        "",
        f"-- {call.stage} needs a model ".ljust(_HEADER_WIDTH, "-"),
        f"   model: {call.model} ({call.backend})",
        f"   slot : {call.slot}",
    ]
    if call.base_url:
        lines.append(f"   url  : {call.base_url}")
        lines.append(f"   port : {call.port if call.port is not None else 'unknown'}")
    else:
        lines.append("   url  : local checkpoint, no server")
    return "\n".join(lines)
