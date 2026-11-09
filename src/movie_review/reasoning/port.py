"""Reasoning LLM port: model-agnostic text completion contract (T033, P6).

First needed by event extraction; shared by all later reasoning stages
(T036-T038, T041+). Model identity comes from the caller (configured
``models.reasoning``); the runtime loads lazily (NFR-006).
"""

from __future__ import annotations

import itertools
import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from movie_review.config.settings import load_settings
from movie_review.domain import ModelUsage
from movie_review.utils import logging as ulog

_logger = logging.getLogger(__name__)

#: One file per reply under the job; the process-wide index keeps names unique
#: when a batch's calls overlap.
_response_index = itertools.count(1)


class ReasoningError(Exception):
    """Base class for reasoning failures."""


class ReasoningUnavailableError(ReasoningError):
    """The configured reasoning model or runtime cannot be loaded here."""

    def __init__(self, model: str, detail: str = "") -> None:
        message = f"Reasoning model unavailable: {model}"
        if detail:
            message += f": {detail}"
        super().__init__(message)
        self.model = model


def extract_json_output(text: str) -> Any:
    """Parse model output as JSON, tolerating surrounding prose or fences."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ReasoningError("Model output contains no JSON value")


def _dump_reasoning_response(
    port: ReasoningPort,
    raw: str,
    *,
    parsed: Any,
    parse_error: str | None,
    duration_ms: int,
) -> None:
    """One record per reasoning call: the raw reply and its parse outcome (T186).

    The reply rides the ``reasoning.response`` event to the console and is
    written under the job, so a suspicious or unparsable answer can be
    inspected without re-running the model. The job and stage come from the
    logging context the pipeline binds around each stage; outside a pipeline
    run (unit tests, benchmarks) there is no job, so the file is skipped and
    the console line still carries the reply.
    """
    context = ulog.current_context()
    response_file = None
    job_id = context.get("job_id")
    if job_id:
        jobs_dir = Path(load_settings().paths.data_dir) / "jobs"
        response_path = (
            jobs_dir / job_id / "reasoning" / "responses" / f"{next(_response_index):04d}.json"
        )
        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(
            json.dumps(
                {
                    "model": port.model,
                    "stage": context.get("stage"),
                    "raw": raw,
                    "parsed": parsed,
                    "parse_error": parse_error,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        response_file = str(response_path)
    ulog.log_event(
        _logger,
        "reasoning.response",
        "ok" if parse_error is None else "error",
        duration_ms=duration_ms,
        model=port.model,
        parse_error=parse_error,
        response_file=response_file,
        response=raw,
    )


class ReasoningPort(ABC):
    """Text completion with structured-output helpers."""

    @property
    def model(self) -> str:
        """Model identity recorded in artifacts and cache keys.

        Concrete adapters override it with the configured checkpoint. See
        :attr:`movie_review.asr.port.ASRPort.model` for why this is part of the
        contract rather than something callers should reach for by type check.
        """
        return type(self).__name__

    @property
    def runtime(self) -> str:
        """The runtime serving this model: "remote", "mlx" or the adapter's own name.

        It is recorded with every model invocation, because the same
        checkpoint served by two runtimes does not give the same answer.
        """
        return type(self).__name__

    def last_usage(self) -> ModelUsage | None:
        """The tokens the last call cost, when the runtime reports them.

        A local runtime often cannot, so None means "not reported", not
        "zero".
        """
        return None

    @abstractmethod
    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        """Complete a prompt with raw model text."""

    def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
        """Complete and parse the output as JSON.

        Every reply is kept on record (T186) before the parse decides its
        fate: the raw text and its parse outcome ride a ``reasoning.response``
        event to the console and are written under the job, so a reply that
        cannot be parsed can be inspected instead of guessed at. The dump
        never changes the outcome -- a parse failure still raises.
        """
        started = time.perf_counter()
        raw = self.complete(prompt, temperature=temperature)
        duration_ms = int((time.perf_counter() - started) * 1000)
        try:
            parsed = extract_json_output(raw)
        except ReasoningError as exc:
            _dump_reasoning_response(
                self, raw, parsed=None, parse_error=str(exc), duration_ms=duration_ms
            )
            raise
        _dump_reasoning_response(
            self, raw, parsed=parsed, parse_error=None, duration_ms=duration_ms
        )
        return parsed

    @abstractmethod
    def unload(self) -> None:
        """Release model resources (memory strategy, plan section 6)."""
