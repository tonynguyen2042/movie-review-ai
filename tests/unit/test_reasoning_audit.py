"""T186 acceptance: every reasoning reply is on record, and the budget is configured.

A run died with ``Model output contains no JSON value`` for one scene, and
the reply the model actually sent had been parsed and discarded --
truncation, a prose refusal, or a server quirk could not be told apart.
Every ``complete_json`` call now records the raw reply (console event plus a
file under the job) before the parse decides its fate, and the factory
resolves ``max_tokens`` the way the vision factory does, so the configuration
file can raise the budget.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from movie_review.config.settings import ModelSpec
from movie_review.reasoning.factory import DEFAULT_MAX_TOKENS, build_reasoning_adapter
from movie_review.reasoning.openai_compat import OpenAICompatAdapter
from movie_review.reasoning.port import ReasoningError, ReasoningPort
from movie_review.utils import logging as ulog
from movie_review.utils.logging import JsonFormatter


class _ScriptedPort__reasoning_audit(ReasoningPort):
    """A port whose replies come from a script, one per call."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)

    @property
    def model(self) -> str:
        return "rec-reasoning"

    def complete(self, prompt: str, *, temperature: float | None = None) -> str:
        return self._replies.pop(0)

    def unload(self) -> None:
        return None


def _response_events__reasoning_audit(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """The call's reasoning.response events as plain field mappings."""
    events: list[dict[str, Any]] = []
    for record in caplog.records:
        if record.__dict__.get("event") != "reasoning.response":
            continue
        events.append(
            {
                # duration_ms is present on the record for every call; the
                # .get keeps the mapping honest if that ever changes.
                field: record.__dict__.get(field)
                for field in (
                    "status",
                    "model",
                    "duration_ms",
                    "parse_error",
                    "response_file",
                    "response",
                )
            }
        )
    return events


def test_a_valid_reply_is_recorded_on_the_console_and_under_the_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("MOVIE_REVIEW_PATHS__DATA_DIR", str(tmp_path / "data"))
    port = _ScriptedPort__reasoning_audit([json.dumps([{"type": "action", "description": "x"}])])
    raw = port._replies[0]

    with caplog.at_level(logging.INFO, logger="movie_review.reasoning.port"):
        with ulog.logging_context(job_id="job_1", stage="events"):
            parsed = port.complete_json("extract the events")
            # The line the operator sees on the console: the formatter merges
            # the pipeline's context into it, so format it while bound.
            console = json.loads(JsonFormatter().format(caplog.records[-1]))

    assert parsed == [{"type": "action", "description": "x"}]
    [event] = _response_events__reasoning_audit(caplog)
    assert event["status"] == "ok"
    assert event["model"] == "rec-reasoning"
    assert event["parse_error"] is None
    assert event["response"] == raw
    assert event["duration_ms"] is not None

    # The console line carries the pipeline context and the full reply.
    assert console["event"] == "reasoning.response"
    assert console["job_id"] == "job_1"
    assert console["stage"] == "events"
    assert console["response"] == raw
    assert console["response_file"] == event["response_file"]

    # The file under the job carries the same record, naming the model.
    # The path itself proves the job context was resolved from the pipeline.
    path = Path(event["response_file"])
    assert path.is_file()
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["model"] == "rec-reasoning"
    assert document["stage"] == "events"
    assert document["raw"] == raw
    assert document["parsed"] == parsed
    assert document["parse_error"] is None


def test_an_unparsable_reply_is_recorded_before_the_error_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The failure mode that ended a run: the reply is now inspectable."""
    monkeypatch.setenv("MOVIE_REVIEW_PATHS__DATA_DIR", str(tmp_path / "data"))
    reply = "I cannot describe what happens in this scene."
    port = _ScriptedPort__reasoning_audit([reply])

    with caplog.at_level(logging.INFO, logger="movie_review.reasoning.port"):
        with ulog.logging_context(job_id="job_1", stage="events"):
            with pytest.raises(ReasoningError, match="no JSON value"):
                port.complete_json("extract the events")

    [event] = _response_events__reasoning_audit(caplog)
    assert event["status"] == "error"
    assert event["parse_error"] is not None
    assert event["response"] == reply

    document = json.loads(Path(event["response_file"]).read_text(encoding="utf-8"))
    assert document["raw"] == reply
    assert document["parsed"] is None
    assert document["parse_error"] is not None


def test_outside_a_pipeline_run_the_reply_still_reaches_the_console(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("MOVIE_REVIEW_PATHS__DATA_DIR", str(tmp_path / "data"))
    port = _ScriptedPort__reasoning_audit([json.dumps({"ok": True})])

    with caplog.at_level(logging.INFO, logger="movie_review.reasoning.port"):
        port.complete_json("hello")

    [event] = _response_events__reasoning_audit(caplog)
    assert event["status"] == "ok"
    assert event["response"] == '{"ok": true}'
    assert event["response_file"] is None
    # No job bound, no job directory created.
    assert not (tmp_path / "data" / "jobs").exists()


# ---------------------------------------------------------------------------
# The completion budget is configuration
# ---------------------------------------------------------------------------


def test_the_configured_max_tokens_reaches_the_remote_adapter() -> None:
    spec = ModelSpec(
        model="rec-9b",
        backend="openai_compatible",
        base_url="http://gpu:8000/v1",
        max_tokens=4096,
    )
    adapter = build_reasoning_adapter(spec)
    assert isinstance(adapter, OpenAICompatAdapter)
    assert adapter._max_tokens == 4096


def test_the_explicit_override_wins_over_the_spec() -> None:
    spec = ModelSpec(
        model="rec-9b",
        backend="openai_compatible",
        base_url="http://gpu:8000/v1",
        max_tokens=4096,
    )
    adapter = build_reasoning_adapter(spec, max_tokens=8192)
    assert isinstance(adapter, OpenAICompatAdapter)
    assert adapter._max_tokens == 8192


def test_max_tokens_falls_back_to_the_default() -> None:
    spec = ModelSpec(model="rec-9b", backend="openai_compatible", base_url="http://gpu:8000/v1")
    adapter = build_reasoning_adapter(spec)
    assert isinstance(adapter, OpenAICompatAdapter)
    assert adapter._max_tokens == DEFAULT_MAX_TOKENS == 2048
