"""The CLI must be able to read a job's results, and read a movie.

T153. README section 50 lists `analyze`, `scenes`, `transcript`, `story`,
`script` and `render`. None of them existed. README section 96 makes
`movie-review inspect movie.mp4` the Phase 0 acceptance command, and
`inspect` took a job id.

The read commands print JSON, so they pipe into `jq` and into anything else
that reads JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from movie_review.cli.app import app
from movie_review.domain import (
    Event,
    EventType,
    Job,
    Scene,
    TranscriptSegment,
)
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect

READ_COMMANDS = ("scenes", "transcript", "story", "script", "render", "analyze")


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("MOVIE_REVIEW_PATHS__DATA_DIR", str(root))
    return root


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


def test_every_read_command_exists() -> None:
    """README section 50 lists them; none of them existed."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in READ_COMMANDS:
        assert command in result.output, f"`{command}` is not a command"


def test_scenes_prints_the_timeline(data_dir: Path) -> None:
    db, job_id = _job(data_dir)
    result = CliRunner().invoke(app, ["scenes", job_id, "--db-path", str(db)])
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["job_id"] == job_id
    assert document["scenes"][0]["scene_id"] == "scene_000001"


def test_transcript_prints_the_lines(data_dir: Path) -> None:
    db, job_id = _job(data_dir)
    result = CliRunner().invoke(app, ["transcript", job_id, "--db-path", str(db)])
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["segments"][0]["text"] == "Hello there."
    assert document["segments"][0]["speaker"] == "SPEAKER_00"


def test_story_prints_the_events(data_dir: Path) -> None:
    db, job_id = _job(data_dir)
    analysis = data_dir / "jobs" / job_id / "movie-analysis.json"
    analysis.parent.mkdir(parents=True, exist_ok=True)
    analysis.write_text(
        json.dumps(
            {
                "events": [{"id": "event_00001", "description": "Someone finds something."}],
                "characters": [],
                "relationships": [],
                "story_arcs": [],
                "themes": [],
                "twists": [],
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["story", job_id, "--db-path", str(db)])
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["events"][0]["id"] == "event_00001"


def test_script_prints_the_review_script(data_dir: Path) -> None:
    db, job_id = _job(data_dir)
    script_path = data_dir / "jobs" / job_id / "review" / "review-script.json"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        json.dumps({"script": {"sections": [{"id": "sec_001", "type": "hook"}]}}),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["script", job_id, "--db-path", str(db)])
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["sections"][0]["id"] == "sec_001"


def test_render_prints_the_manifest(data_dir: Path) -> None:
    db, job_id = _job(data_dir)
    manifest_path = data_dir / "jobs" / job_id / "render" / "render-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"segments": [{"paragraph_id": "p1"}], "total_seconds": 10.0}),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["render", job_id, "--db-path", str(db)])
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["segments"][0]["paragraph_id"] == "p1"


def test_a_missing_artifact_is_reported(data_dir: Path) -> None:
    """A job that has not produced the artifact says so."""
    db, job_id = _job(data_dir)
    result = CliRunner().invoke(app, ["script", job_id, "--db-path", str(db)])
    assert result.exit_code != 0
    assert "Traceback" not in (result.stdout or "") + (result.stderr or "")


def test_inspect_still_takes_a_job_id(data_dir: Path) -> None:
    db, job_id = _job(data_dir)
    result = CliRunner().invoke(app, ["inspect", job_id, "--db-path", str(db)])
    assert result.exit_code == 0, result.output
    record = json.loads(result.stdout)
    assert record["job_id"] == job_id


def test_inspect_accepts_a_movie_path(data_dir: Path) -> None:
    """README section 96: inspect reads the movie's media metadata."""
    movie = data_dir / "movie.mp4"
    movie.write_bytes(b"\x00\x00\x00\x18ftypmp42not-a-video")
    db = data_dir / "jobs.db"
    result = CliRunner().invoke(app, ["inspect", str(movie), "--db-path", str(db)])
    # A file that is not a decodable movie fails the ingest stage, but the
    # command has to reach it rather than complain about a job id.
    assert "Unknown job" not in (result.stdout or "") + (result.stderr or "")
