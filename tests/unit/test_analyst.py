"""T042 acceptance: analyst tools return evidence, never guesses."""

import json
from pathlib import Path

from movie_review.domain import (
    Character,
    Event,
    EventType,
    Evidence,
    EvidenceType,
    Job,
    Scene,
    TranscriptSegment,
)
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from movie_review.story.analyst import StoryAnalyst


def _populated(tmp_path: Path) -> StoryAnalyst:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    repo.save_character(
        conn, "job_1", Character(id="char_001", name="John", first_seen=0.0, last_seen=90.0)
    )
    repo.save_scene(conn, "job_1", Scene(scene_id="s1", start=0.0, end=10.0, duration=10.0))
    repo.save_transcript_segments(
        conn,
        "job_1",
        [TranscriptSegment(segment_id="seg_1", start=1.0, end=2.0, text="Run, Sarah, run")],
    )
    repo.save_event(
        conn,
        "job_1",
        Event(
            id="e1",
            type=EventType.ACTION,
            timestamp=5.0,
            characters=["char_001"],
            description="John runs fast.",
            importance=0.9,
        ),
    )
    repo.save_event(
        conn,
        "job_1",
        Event(
            id="e2", type=EventType.MEETING, timestamp=2.0, description="They meet.", importance=0.3
        ),
    )
    repo.save_evidence(conn, "job_1", Evidence(id="ev1", type=EvidenceType.SCENE, source_id="s1"))
    story = tmp_path / "jobs" / "job_1" / "story"
    story.mkdir(parents=True)
    (story / "story-arcs.json").write_text(
        json.dumps({"arcs": [{"element": "CLIMAX", "applicable": True}]}), encoding="utf-8"
    )
    (story / "themes.json").write_text(
        json.dumps({"themes": [{"theme": "survival"}]}), encoding="utf-8"
    )
    (story / "twists.json").write_text(json.dumps({"twists": []}), encoding="utf-8")
    return StoryAnalyst(conn, "job_1", tmp_path / "jobs")


def test_tools_return_evidence(tmp_path: Path) -> None:
    analyst = _populated(tmp_path)
    assert analyst.get_character("char_001") is not None
    assert analyst.get_character("ghost") is None
    assert analyst.get_scene("s1") is not None
    assert analyst.get_scene("ghost") is None
    assert [s.segment_id for s in analyst.get_dialogue(0.0, 5.0)] == ["seg_1"]
    assert analyst.get_dialogue(50.0, 60.0) == []
    assert analyst.get_event("e1") is not None
    assert analyst.get_event("ghost") is None
    assert [e.id for e in analyst.get_evidence("s1")] == ["ev1"]
    assert analyst.get_evidence("ghost") == []


def test_search_ranks_and_empties(tmp_path: Path) -> None:
    analyst = _populated(tmp_path)
    assert [e.id for e in analyst.search_story("runs fast")] == ["e1"]
    assert analyst.search_story("spaceships") == []
    assert analyst.search_story("   ") == []


def test_analyze_brief(tmp_path: Path) -> None:
    analyst = _populated(tmp_path)
    brief = analyst.analyze()
    assert (brief.character_count, brief.event_count) == (1, 2)
    assert brief.span_seconds == 5.0
    assert brief.protagonists == ["char_001"]
    assert brief.pivotal_events == ["e1", "e2"]
    assert brief.arc_elements == ["CLIMAX"]
    assert brief.themes == ["survival"]
    assert brief.has_twists is False


def test_analyze_without_story_dir(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    analyst = StoryAnalyst(conn, "job_1")
    brief = analyst.analyze()
    assert brief.arc_elements == []
    assert brief.has_twists is False
    assert (brief.character_count, brief.event_count, brief.span_seconds) == (0, 0, 0.0)
    conn.close()
