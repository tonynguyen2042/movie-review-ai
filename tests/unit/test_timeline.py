"""T090 acceptance: movie timeline loads and exports data."""

import json
from pathlib import Path

import pytest

from movie_review.ui.timeline import MovieTimeline
from movie_review.artifacts import manager as artifacts


def test_timeline_from_analysis(tmp_path: Path) -> None:
    """Timeline can be built from movie-analysis.json."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_test"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()
    
    # Create a minimal movie-analysis.json
    analysis = {
        "movie": {
            "title": "Test Movie",
            "metadata": {"duration_seconds": 120.0}
        },
        "scenes": [
            {"scene_id": "scene_000001", "start": 0.0, "end": 30.0, "duration": 30.0},
            {"scene_id": "scene_000002", "start": 30.0, "end": 60.0, "duration": 30.0},
        ],
        "events": [
            {"id": "event_00001", "type": "discovery", "timestamp": 15.0, "characters": ["char_001"], "location": "Lab", "description": "Hero finds clue", "importance": 0.8},
            {"id": "event_00002", "type": "conflict", "timestamp": 45.0, "characters": ["char_001", "char_002"], "location": "Street", "description": "Confrontation", "importance": 0.9},
        ],
        "characters": [
            {"id": "char_001", "name": "Hero", "first_seen": 0.0, "last_seen": 120.0, "confidence": 0.9},
            {"id": "char_002", "name": "Villain", "first_seen": 30.0, "last_seen": 90.0, "confidence": 0.8},
        ],
        "locations": [{"id": "loc_001", "name": "Lab"}],
    }
    
    artifacts.write_json(job_dir / "movie-analysis.json", analysis)
    
    timeline = MovieTimeline(jobs_dir, job_id)
    data = timeline.load()
    
    assert data["job_id"] == job_id
    assert data["movie_title"] == "Test Movie"
    assert data["duration"] == 120.0
    assert len(data["scenes"]) == 2
    assert len(data["events"]) == 2
    assert len(data["characters"]) == 2
    # Events sorted by timestamp
    assert data["events"][0]["timestamp"] == 15.0
    assert data["events"][1]["timestamp"] == 45.0


def test_timeline_json_export(tmp_path: Path) -> None:
    """Timeline can export to JSON."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_test"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()
    
    analysis = {
        "movie": {"title": "Test", "metadata": {"duration_seconds": 60.0}},
        "scenes": [],
        "events": [],
        "characters": [],
    }
    artifacts.write_json(job_dir / "movie-analysis.json", analysis)
    
    timeline = MovieTimeline(jobs_dir, job_id)
    json_str = timeline.to_json()
    
    data = json.loads(json_str)
    assert data["job_id"] == job_id


def test_timeline_html_export(tmp_path: Path) -> None:
    """Timeline can export to HTML."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_test"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()
    
    analysis = {
        "movie": {"title": "Test", "metadata": {"duration_seconds": 60.0}},
        "scenes": [{"scene_id": "s1", "start": 0.0, "end": 10.0, "duration": 10.0}],
        "events": [{"id": "e1", "type": "discovery", "timestamp": 5.0, "characters": [], "location": "", "description": "Found", "importance": 0.5}],
        "characters": [],
    }
    artifacts.write_json(job_dir / "movie-analysis.json", analysis)
    
    timeline = MovieTimeline(jobs_dir, job_id)
    html = timeline.to_html()
    
    assert "Movie Timeline" in html
    assert "Test" in html
    assert "data = " in html


def test_timeline_fallback_from_artifacts(tmp_path: Path) -> None:
    """Timeline falls back to individual artifacts when analysis missing."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_test"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()
    
    # Create individual artifact files (no movie-analysis.json)
    (job_dir / "scenes").mkdir()
    artifacts.write_json(job_dir / "scenes" / "scenes.json", {
        "scenes": [{"scene_id": "s1", "start": 0.0, "end": 10.0, "duration": 10.0}]
    })
    (job_dir / "events").mkdir()
    artifacts.write_json(job_dir / "events" / "events.json", {
        "events": [{"id": "e1", "type": "discovery", "timestamp": 5.0, "characters": [], "location": "", "description": "Found", "importance": 0.5}]
    })
    (job_dir / "characters").mkdir()
    artifacts.write_json(job_dir / "characters" / "characters.json", {
        "characters": [{"id": "c1", "name": "Hero", "first_seen": 0.0, "last_seen": 10.0, "confidence": 0.9}]
    })
    
    timeline = MovieTimeline(jobs_dir, job_id)
    data = timeline.load()
    
    assert len(data["scenes"]) == 1
    assert len(data["events"]) == 1
    assert len(data["characters"]) == 1