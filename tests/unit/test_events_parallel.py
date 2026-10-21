"""The events stage must not be one round trip per scene.

T139 regression. The scenes were extracted in a strict loop, one LLM call
each, and the number of calls was the number of scenes -- hundreds of
sequential calls for a feature film.

The scenes are now extracted in batches, and the scenes in a batch run
concurrently. The continuity context -- which events came before -- comes
from the batch before, so it still crosses the scenes.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from movie_review.domain import EventType, Scene, SceneAnalysis
from movie_review.reasoning.port import ReasoningPort
from movie_review.story.events import run_event_extraction
from tests.helpers import (
    _ctx,
    _scenes,
)


class _SlowReasoner(ReasoningPort):
    """A reasoning adapter that records how many calls overlapped."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.prompts: list[str] = []
        self.max_overlap = 0
        self._active = 0
        self._lock = threading.Lock()

    @property
    def model(self) -> str:
        return "slow"

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        return "[]"

    def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
        with self._lock:
            self._active += 1
            self.max_overlap = max(self.max_overlap, self._active)
            self.prompts.append(prompt)
        try:
            time.sleep(self.delay)
            return [
                {
                    "type": EventType.DISCOVERY.value,
                    "timestamp": 0.0,
                    "characters": [],
                    "location": "loc_01",
                    "description": "Something happens.",
                    "importance": 0.5,
                    "evidence": [],
                }
            ]
        finally:
            with self._lock:
                self._active -= 1

    def unload(self) -> None:
        return None

    def available(self) -> bool:
        return True


def _analyses__events_parallel(scenes: list[Scene]) -> dict[str, SceneAnalysis]:
    return {
        scene.scene_id: SceneAnalysis(
            scene_id=scene.scene_id,
            location="here",
            characters=[],
            actions=["something happens"],
            objects=[],
            emotions=[],
            visual_events=[],
            importance=0.5,
        )
        for scene in scenes
    }


def test_the_scenes_of_a_batch_are_extracted_concurrently(tmp_path: Path) -> None:
    """More than one call must be in flight at the same time."""
    ctx, conn = _ctx(tmp_path)
    try:
        scenes = _scenes(8)
        reasoner = _SlowReasoner()
        result = run_event_extraction(
            scenes,
            _analyses__events_parallel(scenes),
            [],
            [],
            ctx,
            reasoner=reasoner,
            batch_size=8,
        )
        assert len(result.events) == 8
        assert reasoner.max_overlap > 1, "the calls did not overlap"
    finally:
        conn.close()


def test_the_events_are_ordered_by_timestamp(tmp_path: Path) -> None:
    """Concurrency must not reorder the events."""
    ctx, conn = _ctx(tmp_path)
    try:
        scenes = _scenes(6)
        result = run_event_extraction(
            scenes,
            _analyses__events_parallel(scenes),
            [],
            [],
            ctx,
            reasoner=_SlowReasoner(),
            batch_size=6,
        )
        timestamps = [event.timestamp for event in result.events]
        assert timestamps == sorted(timestamps)
    finally:
        conn.close()


def test_the_prior_events_come_from_the_previous_batch(tmp_path: Path) -> None:
    """The scene after a batch is told which events came before it."""
    ctx, conn = _ctx(tmp_path)
    try:
        scenes = _scenes(4)
        reasoner = _SlowReasoner()
        run_event_extraction(
            scenes,
            _analyses__events_parallel(scenes),
            [],
            [],
            ctx,
            reasoner=reasoner,
            batch_size=2,
        )
        assert len(reasoner.prompts) == 4
        # The first batch has no prior events.
        assert "none" in reasoner.prompts[0]
        # The second batch is told about the events of the first.
        assert "Something happens." in reasoner.prompts[2]
    finally:
        conn.close()


def test_a_failure_in_one_scene_fails_the_stage(tmp_path: Path) -> None:
    """A broken scene must fail the stage, not be skipped."""
    from movie_review.story.events import EventExtractionError

    ctx, conn = _ctx(tmp_path)
    try:
        scenes = _scenes(4)

        class _Broken(_SlowReasoner):
            def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
                if "scene_000002" in prompt:
                    raise RuntimeError("the model fell over")
                return super().complete_json(prompt, temperature=temperature)

        try:
            run_event_extraction(
                scenes,
                _analyses__events_parallel(scenes),
                [],
                [],
                ctx,
                reasoner=_Broken(),
                batch_size=4,
            )
        except EventExtractionError as exc:
            assert "scene_000002" in str(exc)
        else:
            raise AssertionError("the stage should have failed")
    finally:
        conn.close()
