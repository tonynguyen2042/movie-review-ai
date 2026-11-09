"""T184 acceptance: every vision request is auditable, and the response is on record.

The audit answers "how many frames did the VLM actually receive": the
``vision.response`` event carries the request's frame count, the scene's
sampled count and the cap, and the response itself is logged to the console
and written under the job directory.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus, Scene, SceneAnalysis
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.orchestrator import PipelineContext
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.vision.analysis import run_visual_analysis
from movie_review.vision.port import AnalysisInput, VLMPort


class _RecordingVlm__vision_audit(VLMPort):
    """A port that records exactly what each request carries."""

    def __init__(self) -> None:
        self.inputs: list[AnalysisInput] = []

    @property
    def model(self) -> str:
        return "rec"

    def analyze(self, analysis_input: AnalysisInput, prompt: str) -> SceneAnalysis:
        self.inputs.append(analysis_input)
        return SceneAnalysis(
            scene_id=analysis_input.scene_id,
            location="here",
            characters=[],
            actions=["something happens"],
            objects=[],
            emotions=[],
            visual_events=[],
            importance=0.5,
        )

    def unload(self) -> None:
        return None

    def available(self) -> bool:
        return True


def _ctx__vision_audit(tmp_path: Path) -> tuple[PipelineContext, sqlite3.Connection]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
    ):
        manager.transition("job_1", state)
    source = tmp_path / "m.mp4"
    source.write_bytes(b"source-bytes")
    ctx = PipelineContext(
        job_id="job_1",
        movie_path=source,
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
    )
    return ctx, conn


def _frames__vision_audit(tmp_path: Path, count: int) -> dict[str, list[Path]]:
    directory = tmp_path / "frames" / "scene_000001"
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(count):
        path = directory / f"f{index:02d}.jpg"
        path.write_bytes(f"frame-{index}".encode())
        paths.append(path)
    return {"scene_000001": paths}


def _scene__vision_audit() -> Scene:
    return Scene(scene_id="scene_000001", start=0.0, end=20.0, duration=20.0)


def _response_events__vision_audit(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """The run's vision.response events as plain field mappings."""
    events: list[dict[str, Any]] = []
    for record in caplog.records:
        if record.__dict__.get("event") != "vision.response":
            continue
        events.append(
            {
                # duration_ms is absent from the record when the event carried
                # none (cache hits), which is exactly what the assertion wants.
                field: record.__dict__.get(field)
                for field in (
                    "scene_id",
                    "model",
                    "frames_sent",
                    "frames_sampled",
                    "max_frames",
                    "cache_hit",
                    "duration_ms",
                    "response_file",
                    "response",
                )
            }
        )
    return events


def test_the_audit_reports_the_exact_request_and_writes_the_response(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ctx, conn = _ctx__vision_audit(tmp_path)
    try:
        adapter = _RecordingVlm__vision_audit()
        with caplog.at_level(logging.INFO, logger="movie_review.vision.analysis"):
            run_visual_analysis(
                [_scene__vision_audit()],
                _frames__vision_audit(tmp_path, 12),
                [],
                ctx,
                port=adapter,
                max_frames=32,
            )

        [event] = _response_events__vision_audit(caplog)
        assert event["scene_id"] == "scene_000001"
        # The audit number is what the port actually received, not a guess.
        assert event["frames_sent"] == len(adapter.inputs[0].frames) == 12
        assert event["frames_sampled"] == 12
        assert event["max_frames"] == 32
        assert event["cache_hit"] is False
        assert event["duration_ms"] is not None
        assert event["response"] is not None

        # The file carries the same response and names the request's frames.
        path = Path(event["response_file"])
        assert path.is_file()
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["frames_sent"] == 12
        assert document["frame_files"] == [path_.name for path_ in adapter.inputs[0].frames]
        assert document["response"] == json.loads(event["response"])
    finally:
        conn.close()


def test_the_audit_reports_the_subset_a_cap_cut(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Twenty frames, cap of eight: the reader sees 8 sent of 20 sampled."""
    ctx, conn = _ctx__vision_audit(tmp_path)
    try:
        adapter = _RecordingVlm__vision_audit()
        with caplog.at_level(logging.INFO, logger="movie_review.vision.analysis"):
            run_visual_analysis(
                [_scene__vision_audit()],
                _frames__vision_audit(tmp_path, 20),
                [],
                ctx,
                port=adapter,
                max_frames=8,
            )

        [event] = _response_events__vision_audit(caplog)
        assert event["frames_sent"] == len(adapter.inputs[0].frames) == 8
        assert event["frames_sampled"] == 20
        assert event["max_frames"] == 8
        document = json.loads(Path(event["response_file"]).read_text(encoding="utf-8"))
        assert document["frames_sent"] == 8
        assert len(document["frame_files"]) == 8
    finally:
        conn.close()


def test_a_cache_hit_is_audited_without_a_new_response(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ctx, conn = _ctx__vision_audit(tmp_path)
    try:
        adapter = _RecordingVlm__vision_audit()
        with caplog.at_level(logging.INFO, logger="movie_review.vision.analysis"):
            run_visual_analysis(
                [_scene__vision_audit()],
                _frames__vision_audit(tmp_path, 6),
                [],
                ctx,
                port=adapter,
                max_frames=32,
            )
            first_content = Path(
                _response_events__vision_audit(caplog)[0]["response_file"]
            ).read_text(encoding="utf-8")
            caplog.clear()

            run_visual_analysis(
                [_scene__vision_audit()],
                _frames__vision_audit(tmp_path, 6),
                [],
                ctx,
                port=adapter,
                max_frames=32,
            )

        [event] = _response_events__vision_audit(caplog)
        # The second run served the cache: no model call, no new response.
        assert len(adapter.inputs) == 1
        assert event["cache_hit"] is True
        assert event["response"] is None
        # The audit still states the request shape the cached answer maps to.
        assert event["frames_sent"] == 6
        # The file a real request wrote is reported, and left untouched.
        path = Path(event["response_file"])
        assert path.is_file()
        assert path.read_text(encoding="utf-8") == first_content
    finally:
        conn.close()
