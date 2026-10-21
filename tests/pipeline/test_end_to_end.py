"""The whole pipeline, end to end, with the models stubbed.

T163. Sixteen of the nineteen stage closures had **never been executed by
any test**: `tests/unit/test_orchestrator.py` monkeypatches
`_get_stage_function` wholesale, so every `run_pipeline` test ran a fake.

That is why the three pipeline blockers all reached master — a render stage
that raised `KeyError` on every run, a quality gate that could not fail, and
a manifest timed with a hard-coded number.

This test drives the real stage functions, in the real order, with only the
models stubbed. The media tooling does its real work on a real, tiny movie.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from movie_review.domain import (
    DiarizedSegment,
    JobStatus,
    SceneAnalysis,
    TranscriptSegment,
)
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.orchestrator import STAGE_SEQUENCE, run_pipeline
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect

#: The movie is this long. The source-footage control limits the footage the
#: review uses to a third of the movie, so a movie this short would fail the
#: ratio check with eight sections in the script.
MOVIE_SECONDS = 90
#: How long each stubbed narration chunk is. There is one chunk per
#: section, and the source-footage control limits the source footage to a
#: third of the narration, so the narration has to be comfortably longer
#: than the movie it is cut from.
NARRATION_SECONDS = 7.5


def _make_movie(path: Path) -> Path:
    """A real, tiny movie, so the media tooling has something to work on."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # The movie needs an audio track: the transcript stage extracts the
    # dialogue from it.
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={MOVIE_SECONDS}:size=320x240:rate=10",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={MOVIE_SECONDS}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


# ---------------------------------------------------------------------------
# The stubbed models
# ---------------------------------------------------------------------------


class _StubASR:
    """Transcribes into a few fixed lines."""

    @property
    def model(self) -> str:
        return "stub-asr"

    def transcribe(self, audio_path: str | Path, *, language: str | None = None):
        return [
            TranscriptSegment(segment_id="seg_1", start=0.5, end=2.0, text="We must leave now."),
            TranscriptSegment(segment_id="seg_2", start=2.5, end=4.0, text="The boat is waiting."),
        ]

    def unload(self) -> None:
        return None

    def available(self) -> bool:
        return True


class _StubVLM:
    """Describes every scene the same way."""

    @property
    def model(self) -> str:
        return "stub-vlm"

    def analyze(self, analysis_input, prompt: str) -> SceneAnalysis:
        return SceneAnalysis(
            scene_id=analysis_input.scene_id,
            location="The harbour",
            characters=["Sarah"],
            actions=["Sarah walks along the quay."],
            objects=[],
            emotions=[],
            visual_events=[],
            importance=0.9,
        )

    def unload(self) -> None:
        return None

    def available(self) -> bool:
        return True


class _StubReasoner:
    """Answers each prompt with the shape that prompt asks for."""

    @property
    def model(self) -> str:
        return "stub-reasoning"

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        return "{}"

    def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
        if "Event Extractor" in prompt:
            return [
                {
                    "id": "event_00001",
                    "type": "DISCOVERY",
                    "timestamp": 1.0,
                    "characters": ["char_001"],
                    "location": "loc_01",
                    "description": "Sarah finds the photograph.",
                    "importance": 0.9,
                    "evidence": ["seg_1"],
                },
                {
                    "id": "event_00002",
                    "type": "CONFLICT",
                    "timestamp": 2.0,
                    "characters": ["char_001", "char_002"],
                    "location": "loc_01",
                    "description": "Sarah and Ben argue.",
                    "importance": 0.8,
                    "evidence": ["seg_2"],
                },
            ]
        if "Story Analyst" in prompt:
            return [
                {
                    "element": "SETUP",
                    "applicable": True,
                    "description": "The plan is made.",
                    "event_ids": ["event_00001", "event_00002"],
                    "confidence": 0.8,
                }
            ]
        if "Theme Analyst" in prompt:
            return [{"theme": "loyalty", "evidence": ["event_00001"], "confidence": 0.7}]
        if "Twist Analyst" in prompt:
            return [
                {
                    "id": "twist_001",
                    "description": "The boat was never coming.",
                    "revealed_at": 3.0,
                    "foreshadowed_by": ["event_00001", "event_00002"],
                    "confidence": 0.6,
                }
            ]
        if "Script Writer" in prompt:
            # The writer asks for one section at a time, and the outline line
            # names which one.
            match = re.search(r"outline: (\S+) \(([^)]+)\)", prompt)
            assert match is not None, prompt[:200]
            section_id, section_type = match.group(1), match.group(2)
            return {
                "sections": [
                    {
                        "id": section_id,
                        "type": section_type,
                        "paragraphs": [
                            {
                                "id": f"{section_id}_p1",
                                "text": f"Narration for the {section_type} section.",
                                "target_seconds": 4,
                                "claims": [],
                                "visual_intent": "the harbour",
                            }
                        ],
                    }
                ]
            }
        if "Critic" in prompt:
            return {"issues": [], "summary": "It works."}
        return {}

    def unload(self) -> None:
        return None

    def available(self) -> bool:
        return True


class _StubTTS:
    """Speaks for a fixed length."""

    @property
    def model(self) -> str:
        return "stub-tts"

    def synthesize(self, request):
        from movie_review.domain.tts import SpeechAudio

        rate = 16000
        frames = int(rate * NARRATION_SECONDS)
        return SpeechAudio(
            duration_seconds=NARRATION_SECONDS,
            sample_rate=rate,
            audio=b"\x00\x00" * frames,
        )

    def unload(self) -> None:
        return None

    def available(self) -> bool:
        return True


class _StubDiarizer:
    """One speaker for the whole recording."""

    @property
    def config(self) -> Any:
        return None

    def diarize(self, audio_path: str | Path) -> list[DiarizedSegment]:
        return [DiarizedSegment(speaker="SPEAKER_00", start=0.0, end=4.0)]

    def unload(self) -> None:
        return None

    def available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


@pytest.mark.ffmpeg
def test_the_whole_pipeline_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every stage closure executes, in order, and the job completes."""
    movie = _make_movie(tmp_path / "movie.mp4")
    db = tmp_path / "jobs.db"
    # The pipeline reads its data directory from the configuration, and the
    # repository's own data directory is not the test's to write into.
    monkeypatch.setenv("MOVIE_REVIEW_PATHS__DATA_DIR", str(tmp_path / "data"))
    # The export writes the output set, and the output directory is
    # configured separately from the data directory.
    monkeypatch.setenv("MOVIE_REVIEW_PATHS__OUTPUT_DIR", str(tmp_path / "output"))
    # The target is a minute, and the narration is eight sections of seven
    # and a half seconds -- so the duration gate can pass and the job can
    # actually complete.
    monkeypatch.setenv("MOVIE_REVIEW_PIPELINE__REVIEW__TARGET_DURATION_MINUTES", "1")
    conn = connect(bootstrap(db))
    manager = JobManager(conn)
    with conn:
        job = manager.create(str(movie))

    # The models are stubbed; the media tooling is not.
    #
    # Each stage binds the factory name at import time, so the name is
    # patched where it is *used*, not where it is defined.
    monkeypatch.setattr("movie_review.asr.transcript.build_asr_adapter", lambda spec: _StubASR())
    monkeypatch.setattr("movie_review.vision.analysis.build_vlm_adapter", lambda spec: _StubVLM())
    for module in (
        "movie_review.story.events",
        "movie_review.story.arcs",
        "movie_review.story.themes",
        "movie_review.story.twists",
        "movie_review.review.writer",
        "movie_review.review.critic",
    ):
        monkeypatch.setattr(f"{module}.build_reasoning_adapter", lambda spec, **kw: _StubReasoner())
    monkeypatch.setattr("movie_review.pipeline.diarization.EnergyDiarizer", _StubDiarizer)
    # The TTS factory is imported inside the stage, so the factory module is
    # where the name has to be patched.
    monkeypatch.setattr("movie_review.tts.factory.build_tts_adapter", lambda spec: _StubTTS())

    results = run_pipeline(job.job_id, str(movie), str(db))

    try:
        failed = [r for r in results if not r.success]
        assert not failed, f"stages failed: {[(r.stage, r.error) for r in failed]}"

        # Every stage in the sequence ran.
        ran = [r.stage for r in results]
        assert ran == [name for name, _ in STAGE_SEQUENCE], ran

        job_dir = tmp_path / "data" / "jobs" / job.job_id
        for name in (
            "media/media.json",
            "scenes/scenes.json",
            "transcript/transcript.json",
            "vision/vision.json",
            "events/events.json",
            "story/story-arcs.json",
            "story/themes.json",
            "story/twists.json",
            "movie-analysis.json",
            "review/review-script.json",
            "verify/script-verification.json",
            "tts/narration.wav",
            "render/render-manifest.json",
            "render/review.srt",
            "render/review.mp4",
            "qc/quality-report.json",
        ):
            assert (job_dir / name).is_file(), f"{name} is missing"

        # The output set the export promises.
        output = tmp_path / "output"
        assert (output / "review.mp4").is_file()
        assert (output / "narration.wav").is_file()
        assert (output / "review-script.md").is_file()
        assert (output / "manifest.json").is_file()

        # The state machine ran the whole chain.
        final = manager.get(job.job_id)
        assert final.status is JobStatus.COMPLETED, final.status

        # The knowledge base carries the story the stages produced.
        analysis = repo.get_artifact(conn, f"{job.job_id}-movie-analysis")
        assert analysis is not None
    finally:
        conn.close()


@pytest.mark.ffmpeg
def test_the_pipeline_stages_are_all_reachable(tmp_path: Path) -> None:
    """Every stage in the sequence has a function behind it.

    A stage in the sequence with no function behind it is a stage that
    never runs, and the pipeline would quietly skip it.
    """
    from movie_review.pipeline.orchestrator import _get_stage_function

    for name, _ in STAGE_SEQUENCE:
        assert _get_stage_function(name) is not None, f"{name} has no function"
