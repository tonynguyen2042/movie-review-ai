"""Deterministic story graph construction (T035, FR-012).

Derives only evidence-grounded edges: event participation, event locations,
and chronological precedence. Interpretive edges (CAUSES, BETRAYS, LOVES and
company) require story reasoning and arrive with later stages.
"""

from __future__ import annotations

from movie_review.domain import Event, Relationship, RelationType, StoryGraph


def build_graph(events: list[Event]) -> StoryGraph:
    """Build participation/location/precedence edges from ordered events."""
    graph = StoryGraph()
    ordered = sorted(events, key=lambda event: (event.timestamp, event.id))
    previous: Event | None = None
    for event in ordered:
        for character_id in event.characters:
            graph.add(
                Relationship(
                    subject=character_id,
                    relation=RelationType.PARTICIPATES_IN,
                    object=event.id,
                    evidence=[event.id, *event.evidence],
                    confidence=event.importance,
                )
            )
        if event.location:
            graph.add(
                Relationship(
                    subject=event.id,
                    relation=RelationType.LOCATED_AT,
                    object=event.location,
                    evidence=[event.id, *event.evidence],
                    confidence=event.importance,
                )
            )
        if previous is not None:
            graph.add(
                Relationship(
                    subject=previous.id,
                    relation=RelationType.PRECEDES,
                    object=event.id,
                    evidence=[previous.id, event.id],
                    confidence=1.0,
                )
            )
        previous = event
    return graph
