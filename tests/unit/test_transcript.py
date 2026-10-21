"""T018 acceptance: transcript stage, audio extraction, schema migration."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from movie_review.asr.port import ASRPort
from movie_review.asr.transcript import TranscriptError, TranscriptResult, run_transcript
from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus, TranscriptSegment
from movie_review.jobs.manager import JobManager
from movie_review.media import ffmpeg as ff
from movie_review.media.audio import AudioExtractionError, extract_dialogue_audio
from movie_review.pipeline.context import StageContext
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect, get_schema_version, migrate
from movie_review.storage.schema import MIGRATION_1, SCHEMA_VERSION
from tests.helpers import (
    _fake_extract,
)


class _FakeASR(ASRPort):
    def __init__(self, segments: list[TranscriptSegment]) -> None:
        self._segments = segments
        self.unloaded = False
        self.seen_language: str | None = "unset"
        self.fail_on_call = False

    def transcribe(
        self, audio_path: str | Path, *, language: str | None = None
    ) -> list[TranscriptSegment]:
        if self.fail_on_call:
            raise AssertionError("ASR must not run on cache hit")
        self.seen_language = language
        return list(self._segments)

    def unload(self) -> None:
        self.unloaded = True


def _segments__transcript() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            segment_id="seg_00000",
            start=0.5,
            end=2.0,
            text="Hello world",
            language="en",
            confidence=0.9,
        ),
        TranscriptSegment(
            segment_id="seg_00001",
            start=2.5,
            end=4.0,
            text="Where were you?",
            language="en",
            confidence=0.8,
        ),
    ]


@dataclass
class Harness:
    conn: sqlite3.Connection
    ctx: StageContext
    source: Path
    port: _FakeASR

    def stage(self, port: ASRPort | None = None) -> TranscriptResult:
        return run_transcript(
            self.source,
            self.ctx,
            language="en",
            port=port or self.port,
            extract_fn=_fake_extract,
        )


def _harness__transcript(tmp_path: Path) -> Harness:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    for state in (JobStatus.INGESTING, JobStatus.MEDIA_READY, JobStatus.SCENES_READY):
        manager.transition("job_1", state)
    source = tmp_path / "m.mp4"
    source.write_bytes(b"source-bytes")
    port = _FakeASR(_segments__transcript())
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )
    return Harness(conn=conn, ctx=ctx, source=source, port=port)


def test_stage_happy_path(tmp_path: Path) -> None:
    harness = _harness__transcript(tmp_path)
    result = harness.stage()
    assert [s.segment_id for s in result.segments] == ["seg_00000", "seg_00001"]
    assert result.cache_hit is False
    assert result.transcript_path.is_file()
    assert result.audio_path.is_file()
    assert harness.port.unloaded is True
    assert harness.port.seen_language == "en"
    assert harness.ctx.manager.get("job_1").status is JobStatus.TRANSCRIPT_READY
    assert repo.list_transcript_segments(harness.conn, "job_1") == result.segments
    assert repo.get_artifact(harness.conn, "job_1-transcript") is not None


def test_stage_second_run_hits_cache(tmp_path: Path) -> None:
    harness = _harness__transcript(tmp_path)
    harness.stage()
    harness.port.fail_on_call = True
    result = harness.stage()
    assert result.cache_hit is True


def test_stage_unknown_job(tmp_path: Path) -> None:
    harness = _harness__transcript(tmp_path)
    harness.ctx.job_id = "job_2"
    with pytest.raises(TranscriptError, match="Unknown job"):
        harness.stage()


def test_stage_failed_job_rejected(tmp_path: Path) -> None:
    harness = _harness__transcript(tmp_path)
    harness.ctx.manager.fail("job_1", "scenes", "earlier")
    with pytest.raises(TranscriptError, match="failed"):
        harness.stage()


def test_stage_asr_failure_fails_job(tmp_path: Path) -> None:
    harness = _harness__transcript(tmp_path)

    class _Bad(_FakeASR):
        def transcribe(
            self, audio_path: str | Path, *, language: str | None = None
        ) -> list[TranscriptSegment]:
            raise RuntimeError("backend exploded")

    harness.port = _Bad(_segments__transcript())
    with pytest.raises(TranscriptError, match="Cannot transcribe"):
        harness.stage()
    job = harness.ctx.manager.get("job_1")
    assert job.status is JobStatus.FAILED
    assert job.failed_stage == "transcript"
    assert harness.port.unloaded is True


def test_stage_hit_regenerates_missing_audio(tmp_path: Path) -> None:
    harness = _harness__transcript(tmp_path)
    first = harness.stage()
    assert first.audio_path.is_file()
    first.audio_path.unlink()
    harness.port.fail_on_call = True
    second = harness.stage()
    assert second.cache_hit is True
    assert second.audio_path.is_file()


def test_stage_rerun_past_transcript_ready(tmp_path: Path) -> None:
    harness = _harness__transcript(tmp_path)
    harness.stage()
    harness.ctx.manager.transition("job_1", JobStatus.VISUAL_ANALYSIS_READY)
    result = harness.stage()
    assert result.cache_hit is True
    assert harness.ctx.manager.get("job_1").status is JobStatus.VISUAL_ANALYSIS_READY


def test_audio_extraction_missing_source(tmp_path: Path) -> None:
    with pytest.raises(AudioExtractionError, match="not found"):
        extract_dialogue_audio(tmp_path / "absent.mp4", tmp_path / "out.wav")


def test_audio_extraction_failure_wrapped(tmp_path: Path) -> None:
    source = tmp_path / "m.mp4"
    source.write_bytes(b"x")

    def _fail(binary: str, args: list[str]) -> str:
        raise ff.ProcessError(binary, args, "boom")

    with pytest.raises(AudioExtractionError, match="Cannot extract audio"):
        extract_dialogue_audio(source, tmp_path / "out.wav", run_fn=_fail)


@pytest.mark.ffmpeg
def test_audio_extraction_real(tmp_path: Path) -> None:
    source = tmp_path / "t.mp4"
    ff.check(
        "ffmpeg",
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x120:rate=10:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
    )
    dest = extract_dialogue_audio(source, tmp_path / "dialogue.wav")
    header = dest.read_bytes()[:4]
    assert header == b"RIFF"
    assert dest.stat().st_size > 44


def test_schema_migrates_from_v1(tmp_path: Path) -> None:
    path = tmp_path / "v1.db"
    with connect(path) as conn:
        for statement in MIGRATION_1:
            conn.execute(statement)
        conn.execute("PRAGMA user_version = 1")
    with connect(path) as conn:
        assert get_schema_version(conn) == 1
        assert migrate(conn) == SCHEMA_VERSION
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "transcript_segments" in tables
    with connect(path) as conn:
        segment = TranscriptSegment(
            segment_id="seg_1", start=0.0, end=1.0, text="hi", confidence=1.0
        )
        with pytest.raises(sqlite3.IntegrityError):
            repo.save_transcript_segments(conn, "missing-job", [segment])
