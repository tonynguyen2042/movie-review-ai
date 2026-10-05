"""Movie knowledge base (T030 locations, T034 registry, T039 analysis)."""

from movie_review.knowledge.locations import extract_locations, scene_locations

__all__ = ["extract_locations", "scene_locations"]
