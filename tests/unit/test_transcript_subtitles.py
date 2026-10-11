"""Transcript SRT/VTT sidecars: formatting + stage integration."""

from pathlib import Path

from movie_review.asr.subtitles import format_srt, format_vtt, write_sidecars
from movie_review.domain import TranscriptSegment


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            segment_id="seg_00000",
            start=0.5,
            end=2.0,
            text="Hello world",
        ),
        TranscriptSegment(
            segment_id="seg_00001",
            start=2.5,
            end=4.0,
            text="  ",  # blank → skipped
        ),
        TranscriptSegment(
            segment_id="seg_00002",
            start=61.5,
            end=62.25,
            text="Where were you?",
        ),
    ]


def test_format_srt_skips_blank_and_numbers_positionally() -> None:
    text = format_srt(_segments())
    assert text == (
        "1\n00:00:00,500 --> 00:00:02,000\nHello world\n"
        "\n"
        "2\n00:01:01,500 --> 00:01:02,250\nWhere were you?\n"
    )


def test_format_vtt_header_and_dot_separator() -> None:
    text = format_vtt(_segments())
    assert text.startswith("WEBVTT\n\n")
    assert "00:00:00.500 --> 00:00:02.000\nHello world" in text
    assert "00:01:01.500 --> 00:01:02.250\nWhere were you?" in text
    assert text.endswith("\n")


def test_format_empty_segments() -> None:
    assert format_srt([]) == ""
    assert format_vtt([]) == "WEBVTT\n"


def test_write_sidecars_idempotent(tmp_path: Path) -> None:
    first_srt, first_vtt = write_sidecars(tmp_path, _segments())
    srt_bytes = first_srt.read_bytes()
    vtt_bytes = first_vtt.read_bytes()
    second_srt, second_vtt = write_sidecars(tmp_path, _segments())
    assert second_srt == first_srt
    assert second_vtt == first_vtt
    assert second_srt.read_bytes() == srt_bytes
    assert second_vtt.read_bytes() == vtt_bytes


def test_stage_writes_sidecars_and_regenerates_on_cache_hit(tmp_path: Path) -> None:
    from movie_review.asr.port import ASRPort
    from movie_review.asr.transcript import run_transcript
    from movie_review.cache.manager import CacheManager
    from movie_review.config.settings import load_settings
    from movie_review.domain import Job, JobStatus
    from movie_review.jobs.manager import JobManager
    from movie_review.pipeline.context import StageContext
    from movie_review.storage import repositories as repo
    from movie_review.storage.database import bootstrap, connect

    class _FakeASR(ASRPort):
        def __init__(self) -> None:
            self.calls = 0

        def transcribe(
            self, audio_path: str | Path, *, language: str | None = None
        ) -> list[TranscriptSegment]:
            self.calls += 1
            return _segments()

        def unload(self) -> None:
            return None

    def _fake_extract(source: Path, dest: Path, ffmpeg: str) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-wav")
        return dest

    conn = connect(bootstrap(tmp_path / "jobs.db"))
    manager = JobManager(conn)
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    for state in (JobStatus.INGESTING, JobStatus.MEDIA_READY, JobStatus.SCENES_READY):
        manager.transition("job_1", state)
    source = tmp_path / "m.mp4"
    source.write_bytes(b"source-bytes")
    port = _FakeASR()
    ctx = StageContext(
        job_id="job_1",
        jobs_dir=tmp_path / "jobs",
        cache=CacheManager(tmp_path / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )
    first = run_transcript(source, ctx, language="en", port=port, extract_fn=_fake_extract)
    assert first.srt_path.is_file()
    assert first.vtt_path.is_file()
    assert first.srt_path.parent == first.transcript_path.parent
    assert "Hello world" in first.srt_path.read_text(encoding="utf-8")
    assert first.vtt_path.read_text(encoding="utf-8").startswith("WEBVTT")
    assert repo.get_artifact(conn, "job_1-transcript-srt") is not None
    assert repo.get_artifact(conn, "job_1-transcript-vtt") is not None

    # Delete sidecars, rerun (cache hit, ASR must not run), expect regeneration.
    first.srt_path.unlink()
    first.vtt_path.unlink()
    calls_before = port.calls
    second = run_transcript(source, ctx, language="en", port=port, extract_fn=_fake_extract)
    assert second.cache_hit is True
    assert port.calls == calls_before
    assert second.srt_path.is_file()
    assert second.vtt_path.is_file()
