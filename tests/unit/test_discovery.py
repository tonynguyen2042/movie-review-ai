"""T028 acceptance: deterministic character discovery from analyses+dialogue."""

from pathlib import Path

from movie_review.characters.discovery import discover_characters, save_discovery
from movie_review.domain import Job, SceneAnalysis, TranscriptSegment
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _analyses() -> tuple[list[SceneAnalysis], dict[str, tuple[float, float]]]:
    analyses = [
        SceneAnalysis(scene_id="scene_000001", characters=["Sarah", "John"]),
        SceneAnalysis(scene_id="scene_000002", characters=["Sarah"]),
    ]
    spans = {"scene_000001": (0.0, 60.0), "scene_000002": (60.0, 120.0)}
    return analyses, spans


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            segment_id="seg_1", start=5.0, end=8.0, text='Where is "Sarah"?', language="en"
        ),
        TranscriptSegment(
            segment_id="seg_2", start=70.0, end=72.0, text="Hello there", language="en"
        ),
        TranscriptSegment(
            segment_id="seg_3", start=80.0, end=84.0, text="John Smith arrived", language="en"
        ),
    ]


def test_discovers_vlm_characters_in_order() -> None:
    analyses, spans = _analyses()
    result = discover_characters(analyses, spans, [])
    # Tie on first_seen broken by name: John before Sarah.
    assert [(c.id, c.name) for c in result.characters][:2] == [
        ("char_001", "John"),
        ("char_002", "Sarah"),
    ]
    sarah = result.characters[1]
    assert (sarah.first_seen, sarah.last_seen) == (0.0, 120.0)
    assert sarah.confidence > 0.5


def test_quoted_dialogue_creates_mentions() -> None:
    analyses, spans = _analyses()
    result = discover_characters(analyses, spans, _segments())
    sarah = next(c for c in result.characters if c.name == "Sarah")
    assert sarah.confidence >= 0.7
    mentions = [m for m in result.mentions if m.character_id == sarah.id]
    assert [(m.source_segment_id, m.timestamp) for m in mentions] == [("seg_1", 5.0)]


def test_phrase_not_single_word() -> None:
    analyses, spans = _analyses()
    result = discover_characters(analyses, spans, _segments())
    names = [c.name for c in result.characters]
    assert "John Smith" in names
    assert "Hello" not in names


def test_discovery_deterministic() -> None:
    analyses, spans = _analyses()
    segments = _segments()
    first = discover_characters(analyses, spans, segments)
    second = discover_characters(analyses, spans, segments)
    assert first == second


def test_save_discovery_persists(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "c.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    analyses, spans = _analyses()
    save_discovery(conn, "job_1", discover_characters(analyses, spans, _segments()))
    assert len(repo.list_characters(conn, "job_1")) == 3
    assert len(repo.list_mentions(conn, "job_1")) == 2
    conn.close()
