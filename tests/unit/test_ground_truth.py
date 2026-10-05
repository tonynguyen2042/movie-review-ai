"""T079 acceptance: ground truth loads and validates against fixtures."""

import pytest

from movie_review.eval.annotations import (
    GroundTruthError,
    load_ground_truth,
    validate_against_analysis,
)
from movie_review.eval.fixtures import golden_analysis


def test_ground_truth_valid() -> None:
    truth = load_ground_truth(
        {
            "movie_id": "golden-01",
            "event_ids": ["e_escape"],
            "character_ids": ["c_ana"],
            "claims": [{"claim_id": "cl1", "text": "Escape.", "evidence": ["ev1"]}],
        }
    )
    validate_against_analysis(truth, golden_analysis())


def test_ground_truth_rejects_unknown_ids() -> None:
    truth = load_ground_truth({"movie_id": "g", "event_ids": ["e_nope"]})
    with pytest.raises(GroundTruthError):
        validate_against_analysis(truth, golden_analysis())


def test_ground_truth_rejects_malformed() -> None:
    with pytest.raises(GroundTruthError):
        load_ground_truth({"event_ids": "not-a-list"})
