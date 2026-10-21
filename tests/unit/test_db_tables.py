"""Every table README section 52 names has to exist.

T157. The schema had fourteen of the twenty-three tables §52 lists. The
missing ones — shots, story_arcs, themes, twists, review_sections,
review_paragraphs, tts_segments, visual_segments and render_segments — were
read back out of the JSON artifacts because they had nowhere else to live,
so a query could not reach them.

The arcs, the themes and the twists now have tables of their own and the
knowledge assembly reads them from the database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from movie_review.domain import Job, StoryArc, StoryElement, Theme, Twist
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect

#: Every table README section 52 names.
SECTION_52_TABLES = [
    "jobs",
    "movies",
    "scenes",
    "shots",
    "transcript_segments",
    "speakers",
    "characters",
    "character_mentions",
    "locations",
    "events",
    "evidence",
    "relationships",
    "story_arcs",
    "themes",
    "twists",
    "review_sections",
    "review_paragraphs",
    "claims",
    "tts_segments",
    "visual_segments",
    "render_segments",
    "artifacts",
    "model_runs",
]


def _db(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(bootstrap(tmp_path / "jobs.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m.mp4"))
    return conn


def test_every_named_table_exists(tmp_path: Path) -> None:
    """Fourteen of the twenty-three existed."""
    conn = _db(tmp_path)
    try:
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = [name for name in SECTION_52_TABLES if name not in names]
        assert not missing, f"the schema is missing: {missing}"
    finally:
        conn.close()


def test_the_arcs_are_queryable(tmp_path: Path) -> None:
    """They used to be read back out of the JSON artifact."""
    conn = _db(tmp_path)
    try:
        arcs = [
            StoryArc(
                element=StoryElement.CLIMAX,
                applicable=True,
                description="The showdown.",
                event_ids=["event_00001"],
            ),
            StoryArc(
                element=StoryElement.SETUP,
                applicable=False,
                description="Not present in this film.",
            ),
        ]
        repo.save_story_arcs(conn, "job_1", arcs)

        stored = repo.list_story_arcs(conn, "job_1")
        assert len(stored) == 2
        assert {arc.element for arc in stored} == {
            StoryElement.CLIMAX,
            StoryElement.SETUP,
        }
        climax = next(arc for arc in stored if arc.element is StoryElement.CLIMAX)
        assert climax.event_ids == ["event_00001"]
        assert climax.applicable is True
    finally:
        conn.close()


def test_the_themes_are_queryable(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    try:
        repo.save_themes(
            conn,
            "job_1",
            [Theme(theme="betrayal", evidence=["event_00001"], confidence=0.8)],
        )
        stored = repo.list_themes(conn, "job_1")
        assert len(stored) == 1
        assert stored[0].theme == "betrayal"
        assert stored[0].evidence == ["event_00001"]
    finally:
        conn.close()


def test_the_twists_are_queryable(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    try:
        repo.save_twists(
            conn,
            "job_1",
            [
                Twist(
                    id="twist_001",
                    description="The letter was a forgery.",
                    revealed_at=120.0,
                    foreshadowed_by=["event_00003"],
                )
            ],
        )
        stored = repo.list_twists(conn, "job_1")
        assert len(stored) == 1
        assert stored[0].id == "twist_001"
        assert stored[0].foreshadowed_by == ["event_00003"]
    finally:
        conn.close()


def test_saving_replaces_the_previous_set(tmp_path: Path) -> None:
    """A re-run must not leave the old rows behind."""
    conn = _db(tmp_path)
    try:
        repo.save_themes(conn, "job_1", [Theme(theme="first")])
        repo.save_themes(conn, "job_1", [Theme(theme="second")])
        stored = repo.list_themes(conn, "job_1")
        assert [theme.theme for theme in stored] == ["second"]
    finally:
        conn.close()
