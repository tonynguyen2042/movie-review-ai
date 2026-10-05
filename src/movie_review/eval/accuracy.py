"""Plot accuracy evaluation (T080, spec acceptance 9).

Scores predicted event IDs against hand-checked ground truth as
precision/recall/F1 over event-ID sets. Pure set arithmetic — no models.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlotAccuracy:
    """Precision/recall/F1 for one prediction set."""

    precision: float
    recall: float
    f1: float
    matched: int
    predicted: int
    expected: int


def plot_accuracy(predicted_ids: list[str], expected_ids: list[str]) -> PlotAccuracy:
    """Score predicted event IDs against expected IDs."""
    predicted = set(predicted_ids)
    expected = set(expected_ids)
    matched = len(predicted & expected)
    precision = matched / len(predicted) if predicted else (1.0 if not expected else 0.0)
    recall = matched / len(expected) if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return PlotAccuracy(
        precision=precision,
        recall=recall,
        f1=f1,
        matched=matched,
        predicted=len(predicted),
        expected=len(expected),
    )
