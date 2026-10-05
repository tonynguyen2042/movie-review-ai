"""T092 acceptance: story graph viewer loads and exports data."""

import json
from pathlib import Path

import pytest

from movie_review.ui.graph import StoryGraph
from movie_review.artifacts import manager as artifacts


def test_graph_from_analysis(tmp_path: Path) -> None:
    """Graph can be built from movie-analysis.json."""
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
        "relationships": [
            {"subject": "char_001", "relation": "KNOWS", "object": "char_002", "evidence": ["ev1"], "confidence": 0.8},
        ],
        "story_arcs": [
            {"events": ["event_00001", "event_00002"]},
        ],
    }
    
    artifacts.write_json(job_dir / "movie-analysis.json", analysis)
    
    graph = StoryGraph(jobs_dir, job_id)
    data = graph.load()
    
    assert data["job_id"] == job_id
    assert "nodes" in data
    assert "edges" in data
    assert "stats" in data
    # Should have 2 characters, 2 events, 1 location, 2 scenes = 7 nodes
    assert data["stats"]["total_nodes"] == 7
    assert data["stats"]["characters"] == 2
    assert data["stats"]["events"] == 2
    assert data["stats"]["locations"] == 1
    assert data["stats"]["scenes"] == 2


def test_graph_json_export(tmp_path: Path) -> None:
    """Graph can export to JSON."""
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
    
    graph = StoryGraph(jobs_dir, job_id)
    json_str = graph.to_json()
    
    data = json.loads(json_str)
    assert data["job_id"] == job_id


def test_graph_html_export(tmp_path: Path) -> None:
    """Graph can export to HTML."""
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
    
    graph = StoryGraph(jobs_dir, job_id)
    html = graph.to_html()
    
    assert "Story Graph" in html
    assert "Test" in html
    assert "data = " in html
    assert "d3js.org/d3.v7.min.js" in html


def test_graph_fallback_from_artifacts(tmp_path: Path) -> None:
    """Graph falls back to individual artifacts when analysis missing."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "job_test"
    job_dir = jobs_dir / job_id
    job_dir.mkdir()
    
    # No movie-analysis.json - should return empty graph
    graph = StoryGraph(jobs_dir, job_id)
    data = graph.load()
    
    assert data["job_id"] == job_id
    assert data["nodes"] == []
    assert data["edges"] == []
    assert data["stats"]["total_nodes"] == 0