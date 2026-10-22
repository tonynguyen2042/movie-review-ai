"""--auto-accept: the switch that lets a model stage start unattended.

One machine cannot hold every model at once, so the CLI pauses before each
stage that needs one. ``--auto-accept`` (or ``interaction.auto_accept``) is
for the runs that do not need the pause: CI, a script, a loop over movies,
the desktop app.

The flag is tri-state on purpose. ``None`` means "not given", so the
configuration decides; ``--no-auto-accept`` lets one run opt out of a
configured default of true.
"""

from __future__ import annotations

import io
import os

import pytest
from typer.testing import CliRunner

from movie_review.cli.app import _ask_before_model, _auto_accept, _model_stage_gate, app
from movie_review.config.settings import AppSettings, InteractionSettings, load_settings
from movie_review.pipeline.model_gate import ModelCall


def _settings__auto_accept(monkeypatch: pytest.MonkeyPatch, auto: bool = False) -> AppSettings:
    for var in list(os.environ):
        if var.startswith("MOVIE_REVIEW_"):
            monkeypatch.delenv(var, raising=False)
    settings = load_settings()
    return settings.model_copy(update={"interaction": InteractionSettings(auto_accept=auto)})


def _call__auto_accept() -> ModelCall:
    return ModelCall(
        stage="vision",
        slot="vision",
        model="Qwen3-VL",
        backend="openai_compatible",
        base_url="http://192.168.1.144:8000/v1",
        port=8000,
    )


def _echo__auto_accept(lines: list[str]):
    def echo(message: str = "", **_: object) -> None:
        lines.append(message)

    return echo


def test_the_default_is_to_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unattended run has to say that it is unattended."""
    for var in list(os.environ):
        if var.startswith("MOVIE_REVIEW_"):
            monkeypatch.delenv(var, raising=False)
    assert load_settings().interaction.auto_accept is False


def test_the_environment_can_set_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that never pauses does not have to pass the flag every time."""
    monkeypatch.setenv("MOVIE_REVIEW_INTERACTION__AUTO_ACCEPT", "true")
    assert load_settings().interaction.auto_accept is True


def test_the_flag_wins_over_the_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three states: not given, given, and denied."""
    configured_off = _settings__auto_accept(monkeypatch, auto=False)
    configured_on = _settings__auto_accept(monkeypatch, auto=True)

    assert _auto_accept(None, configured_off) is False
    assert _auto_accept(None, configured_on) is True
    assert _auto_accept(True, configured_off) is True
    assert _auto_accept(False, configured_on) is False


def test_auto_accept_removes_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """None means "do not ask", which is what every non-CLI caller passes."""
    assert _model_stage_gate(auto_accept=True) is None
    assert _model_stage_gate(auto_accept=False) is _ask_before_model


@pytest.mark.parametrize("answer", ["\n", "y\n", "Y\n", "yes\n", "ok\n"])
def test_a_blank_answer_continues(answer: str) -> None:
    """Enter is the fast path: the operator looked at the model and it is loaded."""
    lines: list[str] = []
    assert _ask_before_model(
        _call__auto_accept(), echo=_echo__auto_accept(lines), stdin=io.StringIO(answer)
    )
    assert any("Qwen3-VL" in line for line in lines)


@pytest.mark.parametrize("answer", ["n\n", "N\n", "no\n", "q\n", "quit\n"])
def test_a_refusal_stops_the_run(answer: str) -> None:
    """Typing 'n' means the model is not loaded yet."""
    lines: list[str] = []
    assert not _ask_before_model(
        _call__auto_accept(), echo=_echo__auto_accept(lines), stdin=io.StringIO(answer)
    )


def test_a_closed_stdin_is_not_consent() -> None:
    """A GUI that spawns the CLI with piped stdio must not hang or be assumed."""
    lines: list[str] = []
    assert not _ask_before_model(
        _call__auto_accept(), echo=_echo__auto_accept(lines), stdin=io.StringIO("")
    )
    assert any("--auto-accept" in line for line in lines)


def test_the_prompt_shows_the_model_the_url_and_the_port() -> None:
    """The three lines are the whole instruction for the model swap."""
    lines: list[str] = []
    _ask_before_model(_call__auto_accept(), echo=_echo__auto_accept(lines), stdin=io.StringIO("\n"))
    block = "\n".join(lines)
    assert "vision needs a model" in block
    assert "Qwen3-VL" in block
    assert "http://192.168.1.144:8000/v1" in block
    assert "port : 8000" in block


@pytest.mark.parametrize("command", ["process", "resume", "retry", "analyze"])
def test_every_pipeline_command_offers_the_flag(command: str) -> None:
    """A command that runs the pipeline has to be able to run it unattended."""
    result = CliRunner().invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert "--auto-accept" in result.output
    assert "--no-auto-accept" in result.output
