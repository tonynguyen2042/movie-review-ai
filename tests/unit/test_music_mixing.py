"""The music bed must be mixed under the narration, and ducked.

T147. `rendering/audio.py::mix` implemented the narration-plus-music mix
with the ducking envelope README section 43 asks for, and nothing called
it. The renderer muxes the narration alone, so the music system did not
exist.

The music is optional, local and off by default: the tracks are local
assets, and nothing about the movie leaves the machine because of them.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import load_settings
from movie_review.domain import Job, JobStatus
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.pipeline.orchestrator import _mix_music
from movie_review.rendering.audio import ducking_envelope, mix
from movie_review.storage.database import bootstrap, connect
from tests.helpers import (
    _wav,
)


def _ctx__music_mixing(
    tmp_path: Path, music: dict[str, object]
) -> tuple[StageContext, sqlite3.Connection]:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo_job = Job(job_id="job_1", input_file="m.mp4")
    conn.execute(
        "INSERT INTO jobs (job_id, input_file, status, failed_stage, error, retry_count, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            repo_job.job_id,
            repo_job.input_file,
            JobStatus.CREATED.value,
            None,
            None,
            0,
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ),
    )
    conn.commit()
    settings = load_settings()
    settings = settings.model_copy(update={"music": settings.music.model_copy(update=music)})
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        conn=conn,
        manager=manager,
        cache=CacheManager(tmp_path / "cache"),
        settings=settings,
    )
    return ctx, conn


def test_the_music_is_off_by_default() -> None:
    """The bed is optional; the default configuration has it off."""
    settings = load_settings()
    assert settings.music.enabled is False
    assert settings.music.track is None


def test_the_music_is_mixed_under_the_narration(tmp_path: Path) -> None:
    """A configured track has to reach the mix."""
    narration = _wav(tmp_path / "jobs" / "job_1" / "tts" / "narration.wav", 4.0)
    track = _wav(tmp_path / "music" / "bed.wav", 4.0, amplitude=0.2)
    ctx, conn = _ctx__music_mixing(tmp_path, {"enabled": True, "track": str(track), "gain": 1.0})
    try:
        mixed = _mix_music(ctx, narration)
        assert mixed != narration
        assert mixed.name == "narration-with-music.wav"
        assert mixed.is_file()
    finally:
        conn.close()


def test_no_music_means_no_mix(tmp_path: Path) -> None:
    """Without a track the narration is rendered as it is."""
    narration = _wav(tmp_path / "jobs" / "job_1" / "tts" / "narration.wav", 2.0)
    ctx, conn = _ctx__music_mixing(tmp_path, {"enabled": False, "track": None, "gain": 1.0})
    try:
        assert _mix_music(ctx, narration) == narration
    finally:
        conn.close()


def test_a_missing_track_does_not_fail_the_render(tmp_path: Path) -> None:
    """The music is optional; a missing file is not a failure."""
    narration = _wav(tmp_path / "jobs" / "job_1" / "tts" / "narration.wav", 2.0)
    ctx, conn = _ctx__music_mixing(
        tmp_path, {"enabled": True, "track": str(tmp_path / "nope.wav"), "gain": 1.0}
    )
    try:
        assert _mix_music(ctx, narration) == narration
    finally:
        conn.close()


def test_the_bed_is_ducked_under_the_speech(tmp_path: Path) -> None:
    """The envelope dips where the narration speaks."""
    # Eight thousand samples at 8 kHz is one second.
    envelope = ducking_envelope(8000, [(0.25, 0.5)], 8000, ducked=0.2)
    assert envelope[0] == 1.0
    assert envelope[3000] == 0.2
    assert envelope[7000] == 1.0


def test_the_mix_keeps_the_narration_intelligible(tmp_path: Path) -> None:
    """The bed is under the speech, not over it."""
    narration = _wav(tmp_path / "narration.wav", 4.0, amplitude=0.5)
    track = _wav(tmp_path / "bed.wav", 4.0, amplitude=0.5)
    dest = tmp_path / "mixed.wav"
    result = mix(narration, dest, music_path=track, music_gain=1.0)
    assert result.path.is_file()
    assert result.duration_seconds == 4.0
