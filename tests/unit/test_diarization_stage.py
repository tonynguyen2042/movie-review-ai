"""The dialogue must be attributed to speakers, and the speakers to characters.

T144. The diarization adapter and the speaker-linking module were both
complete and tested, and no stage called either of them. The speakers
table was always empty, the transcript carried no attribution, and
`pipeline.diarization` in the configuration was a flag that did nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from movie_review.diarization.port import DiarizationPort
from movie_review.domain import (
    Character,
    DiarizedSegment,
    Scene,
    SceneAnalysis,
    TranscriptSegment,
)
from movie_review.pipeline.diarization import DiarizationStageError, run_diarization
from movie_review.storage import repositories as repo
from tests.helpers import (
    _ctx,
)


class _FakeDiarizer(DiarizationPort):
    """A diarizer that returns fixed speaker spans."""

    def __init__(self, turns: list[DiarizedSegment]) -> None:
        self.turns = turns

    def diarize(self, audio_path: str | Path) -> list[DiarizedSegment]:
        return self.turns

    def unload(self) -> None:
        return None

    def available(self) -> bool:
        return True


def _audio__diarization_stage(tmp_path: Path) -> Path:
    path = tmp_path / "jobs" / "job_1" / "tts" / "dialogue.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00")
    return path


def _segments__diarization_stage() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(segment_id="seg_1", start=0.0, end=2.0, text="Hello there."),
        TranscriptSegment(segment_id="seg_2", start=2.0, end=4.0, text="General Kenobi."),
    ]


def test_the_lines_are_attributed_to_their_speaker(tmp_path: Path) -> None:
    """The transcript carried no attribution before this stage existed."""
    ctx, conn = _ctx(tmp_path)
    try:
        repo.save_transcript_segments(conn, "job_1", _segments__diarization_stage())
        turns = [
            DiarizedSegment(speaker="SPEAKER_00", start=0.0, end=2.0),
            DiarizedSegment(speaker="SPEAKER_01", start=2.0, end=4.0),
        ]
        result = run_diarization(
            _audio__diarization_stage(tmp_path), ctx, port=_FakeDiarizer(turns)
        )

        assert result.attributed == 2
        stored = {s.segment_id: s.speaker for s in repo.list_transcript_segments(conn, "job_1")}
        assert stored == {"seg_1": "SPEAKER_00", "seg_2": "SPEAKER_01"}
    finally:
        conn.close()


def test_the_speakers_are_linked_to_the_characters(tmp_path: Path) -> None:
    """A speaker alone with a character in a scene is that character."""
    ctx, conn = _ctx(tmp_path)
    try:
        repo.save_transcript_segments(conn, "job_1", _segments__diarization_stage())
        repo.save_scene(
            conn, "job_1", Scene(scene_id="scene_000001", start=0.0, end=10.0, duration=10.0)
        )
        repo.save_scene_analysis(
            conn,
            "job_1",
            SceneAnalysis(
                scene_id="scene_000001",
                location="here",
                characters=["Sarah"],
                actions=[],
                objects=[],
                emotions=[],
                visual_events=[],
                importance=0.5,
            ),
        )
        repo.save_character(
            conn,
            "job_1",
            Character(
                id="char_001",
                name="Sarah",
                aliases=[],
                first_seen=0.0,
                last_seen=10.0,
            ),
        )
        turns = [DiarizedSegment(speaker="SPEAKER_00", start=0.0, end=4.0)]
        result = run_diarization(
            _audio__diarization_stage(tmp_path), ctx, port=_FakeDiarizer(turns)
        )

        assert result.linked == 1
        links = repo.list_speaker_links(conn, "job_1")
        assert links[0][0] == "SPEAKER_00"
        assert links[0][1] == "char_001"
    finally:
        conn.close()


def test_an_ambiguous_speaker_keeps_no_character(tmp_path: Path) -> None:
    """The linking abstains rather than guessing."""
    ctx, conn = _ctx(tmp_path)
    try:
        repo.save_transcript_segments(conn, "job_1", _segments__diarization_stage())
        repo.save_scene(
            conn, "job_1", Scene(scene_id="scene_000001", start=0.0, end=10.0, duration=10.0)
        )
        repo.save_scene_analysis(
            conn,
            "job_1",
            SceneAnalysis(
                scene_id="scene_000001",
                location="here",
                characters=["Sarah", "John"],
                actions=[],
                objects=[],
                emotions=[],
                visual_events=[],
                importance=0.5,
            ),
        )
        for index, name in enumerate(("Sarah", "John")):
            repo.save_character(
                conn,
                "job_1",
                Character(
                    id=f"char_{index:03d}",
                    name=name,
                    aliases=[],
                    first_seen=0.0,
                    last_seen=10.0,
                ),
            )
        turns = [DiarizedSegment(speaker="SPEAKER_00", start=0.0, end=4.0)]
        run_diarization(_audio__diarization_stage(tmp_path), ctx, port=_FakeDiarizer(turns))

        links = repo.list_speaker_links(conn, "job_1")
        assert links[0][1] is None
    finally:
        conn.close()


def test_a_missing_audio_file_is_reported(tmp_path: Path) -> None:
    """A missing file is a classified failure, not a crash."""
    ctx, conn = _ctx(tmp_path)
    try:
        with pytest.raises(DiarizationStageError, match="No dialogue audio"):
            run_diarization(
                tmp_path / "jobs" / "job_1" / "tts" / "missing.wav",
                ctx,
                port=_FakeDiarizer([]),
            )
    finally:
        conn.close()


def test_the_stage_is_in_the_pipeline() -> None:
    """A stage nobody can reach is not a stage."""
    from movie_review.pipeline.orchestrator import STAGE_SEQUENCE

    order = [name for name, _ in STAGE_SEQUENCE]
    assert "diarization" in order
    # The linking needs the characters, so the stage follows them.
    assert order.index("diarization") > order.index("characters")
