"""Evaluation package: golden fixtures and quality evaluators (T078-T083)."""

from movie_review.eval import (
    accuracy,
    annotations,
    coverage_eval,
    fixtures,
    hallucination,
    regression,
)

__all__ = [
    "accuracy",
    "annotations",
    "coverage_eval",
    "fixtures",
    "hallucination",
    "regression",
]
