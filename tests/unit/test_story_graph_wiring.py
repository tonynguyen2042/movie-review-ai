"""The story graph must be built, and it must reach the analysis document.

T145. `knowledge/graph.py::build_graph` was complete and tested, and
nothing called it. `repo.save_relationship` was never called either, so the
relationships table was always empty and `movie-analysis.json` always
reported `"relationships": []`.

README section 22 asks for a story graph of characters, events, locations
and the edges between them. The graph is derived from the events, so it is
built in the events stage and persisted there.
"""

from __future__ import annotations

from pathlib import Path

from movie_review.domain import Event, EventType
from movie_review.knowledge.graph import build_graph
from movie_review.storage import repositories as repo
from tests.helpers import (
    _ctx,
)


def _events__story_graph_wiring() -> list[Event]:
    return [
        Event(
            id="event_00001",
            type=EventType.DISCOVERY,
            timestamp=10.0,
            characters=["char_001"],
            location="loc_01",
            description="Sarah finds the photograph.",
            importance=0.9,
        ),
        Event(
            id="event_00002",
            type=EventType.CONFLICT,
            timestamp=40.0,
            characters=["char_001", "char_002"],
            location="loc_02",
            description="They argue.",
            importance=0.7,
        ),
    ]


def test_the_graph_is_built_from_the_events() -> None:
    """The builder was complete and nothing called it."""
    graph = build_graph(_events__story_graph_wiring())
    subjects = {(edge.subject, edge.relation.value, edge.object) for edge in graph.relationships}

    assert ("char_001", "PARTICIPATES_IN", "event_00001") in subjects
    assert ("event_00001", "LOCATED_AT", "loc_01") in subjects
    assert ("event_00001", "PRECEDES", "event_00002") in subjects


def test_a_discovery_is_a_discovery_by_whoever_is_in_it() -> None:
    """A discovery is grounded in the event's own type."""
    graph = build_graph(_events__story_graph_wiring())
    subjects = {(edge.subject, edge.relation.value, edge.object) for edge in graph.relationships}
    assert ("char_001", "DISCOVERS", "event_00001") in subjects
    # The conflict is not a discovery, so nobody discovers it.
    assert ("char_001", "DISCOVERS", "event_00002") not in subjects


def test_every_edge_carries_its_evidence() -> None:
    """The constitution's P1: an edge has to point at what grounds it."""
    graph = build_graph(_events__story_graph_wiring())
    for edge in graph.relationships:
        assert edge.evidence, f"{edge.relation} {edge.subject} -> {edge.object} has no evidence"


def test_the_relationships_are_persisted(tmp_path: Path) -> None:
    """The relationships table was always empty."""
    ctx, conn = _ctx(tmp_path)
    try:
        for relationship in build_graph(_events__story_graph_wiring()).relationships:
            repo.save_relationship(conn, "job_1", relationship)
        stored = repo.list_relationships(conn, "job_1")
        assert stored
        assert {edge.relation.value for edge in stored} >= {
            "PARTICIPATES_IN",
            "LOCATED_AT",
            "PRECEDES",
        }
    finally:
        conn.close()
