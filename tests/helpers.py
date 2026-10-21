"""The builders the test suite shares.

Each helper below was defined, near enough, in several test files. They
live here so that a change to a builder is a change in one place, and so
that a name means one thing across the suite.

A helper that belongs to one test file stays in that file, under a name
that says which file it belongs to. The rule is not "everything shared"
but "one name, one meaning".

Import them by name::

    from tests.helpers import _events, _paragraph
"""

from __future__ import annotations

import sqlite3
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from movie_review.artifacts.integrity import ArtifactRecord
from movie_review.artifacts.manager import sha256_bytes
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import ModelSpec, load_settings
from movie_review.domain import (
    Character,
    Claim,
    ClaimType,
    Event,
    EventType,
    Job,
    JobStatus,
    ManifestSegment,
    MovieMetadata,
    RenderManifest,
    ReviewParagraph,
    Scene,
    SceneAnalysis,
    TranscriptSegment,
)
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.pipeline.orchestrator import PipelineContext, _get_stage_function
from movie_review.publishing.metadata import VideoMetadata
from movie_review.publishing.port import (
    UploadRequest,
)
from movie_review.rendering.clips import SelectedClip
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.vision.port import AnalysisInput


def _analyses() -> tuple[list[SceneAnalysis], dict[str, tuple[float, float]]]:
    analyses = [
        SceneAnalysis(scene_id="scene_000001", characters=["Sarah", "John"]),
        SceneAnalysis(scene_id="scene_000002", characters=["Sarah"]),
    ]
    spans = {"scene_000001": (0.0, 60.0), "scene_000002": (60.0, 120.0)}
    return analyses, spans


def _analysis() -> dict[str, Any]:
    return {
        "movie": {"id": "movie_x"},
        "scenes": [
            {"scene_id": "s1", "analysis": {"characters": ["Marina Vane"]}},
            {"scene_id": "s2", "analysis": {"characters": ["Marina"]}},
        ],
        "characters": [
            {
                "id": "char_000001",
                "name": "Marina Vane",
                "aliases": ["Marina"],
                "gender": "female",
                "first_seen": 12.0,
                "last_seen": 900.0,
                "confidence": 0.94,
            },
            {
                "id": "char_000002",
                "name": "The Captain",
                "aliases": [],
                "gender": "male",
                "first_seen": 300.0,
                "last_seen": 1200.0,
                "confidence": 0.5,
            },
        ],
        "events": [
            {"id": "ev1", "type": "DISCOVERY", "characters": ["char_000001"]},
        ],
        "relationships": [
            {
                "subject": "char_000001",
                "relation": "KNOWS",
                "object": "char_000002",
                "evidence": ["evidence_1"],
                "confidence": 0.8,
            },
        ],
    }


def _audio(path: Path, seconds: float, rate: int = 8000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def _character() -> Character:
    return Character(
        id="char_001",
        name="John",
        aliases=["Johnny"],
        first_seen=122.4,
        last_seen=4812.3,
        confidence=0.91,
    )


def _claim(claim_id: str, text: str = "Sarah knew.") -> Claim:
    return Claim(claim_id=claim_id, text=text, type=ClaimType.PLOT_FACT, evidence=["event_001"])


def _clip(paragraph_id: str, start: float, end: float) -> SelectedClip:
    return SelectedClip(paragraph_id, "scene_000001", start, end)


def _conn(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    return conn


def _ctx(tmp_path: Path) -> tuple[StageContext, sqlite3.Connection]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    for state in (
        JobStatus.INGESTING,
        JobStatus.MEDIA_READY,
        JobStatus.SCENES_READY,
        JobStatus.TRANSCRIPT_READY,
        JobStatus.VISUAL_ANALYSIS_READY,
        JobStatus.CHARACTERS_READY,
    ):
        manager.transition("job_1", state)
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=load_settings(),
    )
    return ctx, conn


def _db(tmp: Path) -> str:
    return str(tmp / "jobs.db")


def _event(
    event_id: str,
    type: EventType,
    timestamp: float,
    characters: list[str] | None = None,
    evidence: list[str] | None = None,
) -> Event:
    return Event(
        id=event_id,
        type=type,
        timestamp=timestamp,
        characters=characters or [],
        description=f"{event_id} happened.",
        evidence=evidence or [],
    )


def _events() -> list[Event]:
    return [
        Event(id="event_00001", type=EventType.INTRODUCTION, timestamp=5.0, description="Setup."),
        Event(
            id="event_00002",
            type=EventType.CLIMAX,
            timestamp=90.0,
            description="Showdown.",
            importance=0.95,
        ),
    ]


def _fake_extract(source: Path, dest: Path, ffmpeg: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"fake-wav")
    return dest


def _fake_probe(path: str) -> MovieMetadata:
    return MovieMetadata(
        file=path,
        sha256="a" * 64,
        duration_seconds=60.0,
        width=640,
        height=480,
        fps=25.0,
        video_codec="h264",
    )


def _fake_run(binary: str, args: list[str]) -> str:
    dest = Path(args[-1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"frame-bytes")
    return ""


def _frame(tmp_path: Path) -> Path:
    # 1x1 PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000a49444154789c6360000002000154a24f5f0000000049454e44ae426082"
    )
    path = tmp_path / "frame.png"
    path.write_bytes(png)
    return path


def _input(tmp_path: Path) -> AnalysisInput:
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"fake-frame")
    return AnalysisInput(scene_id="scene_000001", frames=[frame], dialogue="hi")


def _job(data_dir: Path) -> tuple[Path, str]:
    db = data_dir / "jobs.db"
    conn = connect(bootstrap(db))
    repo.save_job(conn, Job(job_id="job_1", input_file=str(data_dir / "movie.mp4")))
    repo.save_scene(
        conn, "job_1", Scene(scene_id="scene_000001", start=0.0, end=10.0, duration=10.0)
    )
    repo.save_transcript_segments(
        conn,
        "job_1",
        [
            TranscriptSegment(
                segment_id="seg_1", start=0.0, end=2.0, text="Hello there.", speaker="SPEAKER_00"
            )
        ],
    )
    repo.save_event(
        conn,
        "job_1",
        Event(
            id="event_00001",
            type=EventType.DISCOVERY,
            timestamp=5.0,
            description="Someone finds something.",
        ),
    )
    conn.commit()
    conn.close()
    return db, "job_1"


def _manager(tmp_path: Path) -> JobManager:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    return JobManager(conn)


def _manifest() -> RenderManifest:
    return RenderManifest(
        segments=[
            ManifestSegment(
                paragraph_id="p1",
                start=0.0,
                duration=4.0,
                scene_id="s1",
                clip_start=1.0,
                clip_end=4.0,
            ),
            ManifestSegment(
                paragraph_id="p2",
                start=4.0,
                duration=2.0,
                scene_id="s2",
                clip_start=0.0,
                clip_end=10.0,
            ),
        ],
        total_seconds=6.0,
        source_seconds=7.0,
    )


def _meta(duration: float) -> MovieMetadata:
    return MovieMetadata(
        file="review.mp4",
        sha256="a" * 64,
        duration_seconds=duration,
        width=1920,
        height=1080,
        fps=30.0,
        video_codec="h264",
    )


def _movie(tmp_path: Path) -> Path:
    movie = tmp_path / "movie.mp4"
    movie.write_bytes(b"\x00\x00\x00\x18ftypmp42not-a-video")
    return movie


def _outputs() -> list[object]:
    return [
        [
            {
                "element": "SETUP",
                "applicable": True,
                "description": "Intro.",
                "event_ids": ["event_00001"],
                "confidence": 0.9,
            },
            {
                "element": "CLIMAX",
                "applicable": True,
                "description": "Showdown.",
                "event_ids": ["event_00002"],
                "confidence": 0.95,
            },
            {
                "element": "RESOLUTION",
                "applicable": False,
                "description": "",
                "event_ids": [],
                "confidence": 0.4,
            },
        ]
    ]


def _paragraph(paragraph_id: str, *refs: str) -> ReviewParagraph:
    return ReviewParagraph(
        id=paragraph_id,
        text="Narration here.",
        target_seconds=12,
        claims=[
            Claim(
                claim_id=f"{paragraph_id}c{i}",
                text="Fact.",
                type=ClaimType.PLOT_FACT,
                evidence=[ref],
            )
            for i, ref in enumerate(refs)
        ],
        visual_intent="shot",
    )


def _remote_spec() -> ModelSpec:
    return ModelSpec(
        model="whisper-large-v3-turbo", backend="openai_compatible", base_url="http://host:9000/v1"
    )


def _request(video: Path, **kwargs: Any) -> UploadRequest:
    return UploadRequest(
        video_path=video,
        metadata=VideoMetadata(title="A title", description="A description", tags=["t"]),
        **kwargs,
    )


def _scene(scene_id: str, start: float, end: float) -> Scene:
    return Scene(scene_id=scene_id, start=start, end=end, duration=end - start)


def _scenes(count: int) -> list[Scene]:
    return [
        Scene(
            scene_id=f"scene_{index:06d}",
            start=float(index * 10),
            end=float(index * 10 + 9),
            duration=9.0,
        )
        for index in range(count)
    ]


def _segment() -> TranscriptSegment:
    return TranscriptSegment(
        segment_id="seg_00042",
        start=123.44,
        end=127.12,
        text="Where were you last night?",
        language="en",
        confidence=0.94,
    )


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            segment_id="seg_00000",
            start=0.5,
            end=2.0,
            text="Hello world",
            language="en",
            confidence=0.9,
        )
    ]


def _video(tmp_path: Path) -> Path:
    video = tmp_path / "review.mp4"
    video.write_bytes(b"fake-mp4")
    return video


def _vision_stage() -> Callable[[PipelineContext], object]:
    """The vision stage, asserting it exists rather than passing None onwards."""
    stage = _get_stage_function("vision")
    assert stage is not None, "vision stage is missing from the orchestrator"
    return stage


def _wav(path: Path, seconds: float, rate: int = 8000, amplitude: float = 0.5) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = int(rate * seconds)
    samples = (np.sin(np.arange(count) * 2 * np.pi * 220 / rate) * amplitude).astype(np.float64)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())
    return path


def _write(root: Path, stage: str, name: str, data: bytes) -> ArtifactRecord:
    target = root / "job1" / stage / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return ArtifactRecord(relative_path=f"{stage}/{name}", expected_hash=sha256_bytes(data))
