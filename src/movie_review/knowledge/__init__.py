"""Movie knowledge base (T030 locations, T034 registry, T035 graph, T039 analysis)."""

from movie_review.knowledge.graph import build_graph
from movie_review.knowledge.locations import extract_locations, scene_locations
from movie_review.knowledge.registry import find_by_source, find_by_type, register_evidence

__all__ = [
    "build_graph",
    "extract_locations",
    "find_by_source",
    "find_by_type",
    "register_evidence",
    "scene_locations",
]
