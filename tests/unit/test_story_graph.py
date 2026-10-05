"""T092 acceptance: story graph viewer builds from movie-analysis.json.

Field names follow the canonical schema produced by
``movie_review.knowledge.analysis``.
"""

import json
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.ui.graph import StoryGraph


def _analysis() -> dict:
    return {
        "movie": {"id": "movie_x", "title": "Blackrock"},
        "characters": [
            {
                "id": "c1",
                "name": "Marina Vane",
                "first_seen": 12.0,
                "last_seen": 900.0,
                "confidence": 0.94,
            },
            {
                "id": "c2",
                "name": "The Captain",
                "first_seen": 300.0,
                "last_seen": 1200.0,
                "confidence": 0.5,
            },
        ],
        "events": [
            {
                "id": "e1",
                "type": "DISCOVERY",
                "timestamp": 600.0,
                "description": "The lighthouse log is found",
                "importance": 0.8,
                "location": "l1",
            },
        ],
        "locations": [
            {"id": "l1", "name": "Blackrock Lighthouse", "first_seen": 10.0, "last_seen": 1200.0},
        ],
        "scenes": [
            {
                "scene_id": "s1",
                "start": 0.0,
                "end": 30.0,
                "duration": 30.0,
                "analysis": {"location": "Blackrock Lighthouse"},
            },
        ],
        "relationships": [
            {
                "subject": "c1",
                "relation": "KNOWS",
                "object": "c2",
                "evidence": ["ev_1"],
                "confidence": 0.8,
            },
            # dangling endpoints must be dropped, not rendered as broken edges
            {
                "subject": "c1",
                "relation": "KILLS",
                "object": "ghost",
                "evidence": [],
                "confidence": 0.4,
            },
        ],
    }


def _seed(tmp_path: Path, job_id: str = "job_x", doc: dict | None = None) -> Path:
    jobs_dir = tmp_path / "jobs"
    job_dir = jobs_dir / job_id
    job_dir.mkdir(parents=True)
    artifacts.write_json(job_dir / "movie-analysis.json", doc if doc is not None else _analysis())
    return jobs_dir


def test_story_graph_builds_all_node_types(tmp_path: Path) -> None:
    """Characters, events, locations, and scenes become typed nodes."""
    jobs_dir = _seed(tmp_path)
    data = StoryGraph(jobs_dir, "job_x").load()

    assert data["job_id"] == "job_x"
    assert data["movie_title"] == "Blackrock"

    stats = data["stats"]
    assert stats["characters"] == 2
    assert stats["events"] == 1
    assert stats["locations"] == 1
    assert stats["scenes"] == 1
    assert stats["total_nodes"] == 5
    # KNOWS (c1->c2) + OCCURS_AT (e1->l1)
    assert stats["total_edges"] == 2

    by_id = {n["id"]: n for n in data["nodes"]}
    assert "char:c1" in by_id
    assert by_id["char:c1"]["label"] == "Marina Vane"
    assert by_id["char:c1"]["type"] == "character"
    assert by_id["char:c1"]["group"] == "character"
    assert by_id["char:c1"]["metadata"]["confidence"] == 0.94

    assert by_id["event:e1"]["label"].startswith("DISCOVERY")
    assert by_id["location:l1"]["label"] == "Blackrock Lighthouse"
    assert by_id["scene:s1"]["label"] == "Scene s1"
    assert by_id["scene:s1"]["metadata"]["location"] == "Blackrock Lighthouse"


def test_story_graph_node_ids_are_namespaced(tmp_path: Path) -> None:
    """IDs are prefixed by type so cross-type collisions cannot occur."""
    jobs_dir = _seed(tmp_path)
    data = StoryGraph(jobs_dir, "job_x").load()
    ids = [n["id"] for n in data["nodes"]]
    assert "char:c1" in ids
    assert "event:e1" in ids
    assert "location:l1" in ids
    assert "scene:s1" in ids
    assert len(ids) == len(set(ids))


def test_story_graph_edges_use_resolved_nodes(tmp_path: Path) -> None:
    """Relationships become edges between resolved character nodes."""
    jobs_dir = _seed(tmp_path)
    data = StoryGraph(jobs_dir, "job_x").load()

    # KNOWS from the relationship + OCCURS_AT from the event's location.
    # The KILLS edge pointing at a nonexistent character is dropped.
    relations = {(e["source"], e["relation"], e["target"]) for e in data["edges"]}
    assert relations == {
        ("char:c1", "KNOWS", "char:c2"),
        ("event:e1", "OCCURS_AT", "location:l1"),
    }

    knows = next(e for e in data["edges"] if e["relation"] == "KNOWS")
    assert knows["weight"] == 0.8
    assert not any("ghost" in (e["source"] + e["target"]) for e in data["edges"])


def test_story_graph_deduplicates_nodes(tmp_path: Path) -> None:
    """A repeated character id yields a single node."""
    doc = _analysis()
    doc["characters"].append(
        {
            "id": "c1",
            "name": "Marina Vane (again)",
            "first_seen": 1.0,
            "last_seen": 2.0,
            "confidence": 0.5,
        }
    )
    jobs_dir = _seed(tmp_path, doc=doc)

    data = StoryGraph(jobs_dir, "job_x").load()
    char_nodes = [n for n in data["nodes"] if n["type"] == "character"]
    assert len(char_nodes) == 2


def test_story_graph_json_export(tmp_path: Path) -> None:
    """JSON export round-trips the loaded structure."""
    jobs_dir = _seed(tmp_path)
    payload = json.loads(StoryGraph(jobs_dir, "job_x").to_json())
    assert payload["job_id"] == "job_x"
    assert payload["stats"]["total_nodes"] == 5


def test_story_graph_html_export(tmp_path: Path) -> None:
    """HTML export renders the graph shell and embeds node/edge data."""
    jobs_dir = _seed(tmp_path)
    html = StoryGraph(jobs_dir, "job_x").to_html()

    assert "Story Graph" in html
    assert "job_x" in html
    assert "Total Nodes" in html
    assert "5" in html
    assert "data = " in html


def test_story_graph_html_escapes_label_content(tmp_path: Path) -> None:
    """Model-produced labels cannot open a new script block."""
    doc = _analysis()
    doc["movie"]["title"] = "<script>alert(1)</script>Blackrock"
    jobs_dir = _seed(tmp_path, doc=doc)

    html = StoryGraph(jobs_dir, "job_x").to_html()

    # this template legitimately has two script elements (inline + d3 CDN);
    # data must not add a third.
    assert html.count("</script>") == 2
    assert "<script>alert(1)</script>" not in html
    assert "\\u003cscript\\u003e" in html


def test_story_graph_empty(tmp_path: Path) -> None:
    """No artifact yields an empty but well-formed structure."""
    jobs_dir = tmp_path / "jobs"
    (jobs_dir / "job_none").mkdir(parents=True)

    data = StoryGraph(jobs_dir, "job_none").load()
    assert data["job_id"] == "job_none"
    assert data["nodes"] == []
    assert data["edges"] == []
    assert data["stats"]["total_nodes"] == 0


def test_story_graph_empty_document(tmp_path: Path) -> None:
    """A document with no entities still produces a valid graph."""
    jobs_dir = _seed(tmp_path, doc={"movie": {"id": "m"}})
    data = StoryGraph(jobs_dir, "job_x").load()
    assert data["stats"]["total_nodes"] == 0
    assert data["stats"]["total_edges"] == 0
    assert data["movie_title"] == "Unknown"
