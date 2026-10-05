"""Story relationship graph model (spec FR-012; README section 22)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from movie_review.domain.evidence import Confidence


class RelationType(StrEnum):
    """Story edge vocabulary (FR-012 plus README section 22)."""

    PARTICIPATES_IN = "PARTICIPATES_IN"
    DISCOVERS = "DISCOVERS"
    KNOWS = "KNOWS"
    SUSPECTS = "SUSPECTS"
    LIES_TO = "LIES_TO"
    TRUSTS = "TRUSTS"
    BETRAYS = "BETRAYS"
    KILLS = "KILLS"
    LOVES = "LOVES"
    HATES = "HATES"
    LOCATED_AT = "LOCATED_AT"
    CAUSES = "CAUSES"
    PRECEDES = "PRECEDES"
    FORESHADOWS = "FORESHADOWS"
    REVEALS = "REVEALS"


class Relationship(BaseModel):
    """One directed story edge with evidence."""

    subject: str = Field(min_length=1)
    relation: RelationType
    object: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    confidence: Confidence = 1.0


class StoryGraph(BaseModel):
    """Relationship collection with traversal helpers."""

    relationships: list[Relationship] = Field(default_factory=list)

    def add(self, relationship: Relationship) -> None:
        """Append an edge (duplicates preserved for multi-evidence paths)."""
        self.relationships.append(relationship)

    def nodes(self) -> list[str]:
        """All node IDs in first-seen order."""
        ordered: list[str] = []
        for edge in self.relationships:
            for node in (edge.subject, edge.object):
                if node not in ordered:
                    ordered.append(node)
        return ordered

    def neighbors(self, node_id: str) -> list[str]:
        """Node IDs directly connected to ``node_id`` (either direction)."""
        found: list[str] = []
        for edge in self.relationships:
            if edge.subject == node_id and edge.object not in found:
                found.append(edge.object)
            elif edge.object == node_id and edge.subject not in found:
                found.append(edge.subject)
        return found

    def relations_between(self, subject: str, object: str) -> list[RelationType]:
        """Relation types on direct edges from ``subject`` to ``object``."""
        return [
            edge.relation
            for edge in self.relationships
            if edge.subject == subject and edge.object == object
        ]
