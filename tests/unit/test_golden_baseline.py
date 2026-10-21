"""The golden baseline has to live on disk, and it has to stay put.

T164. README §77 asks for a golden dataset: manually verified movies with
their scenes, characters, major events, ending and twist, used as a
regression baseline. The directory was empty.

The only "golden" data was a Python dict inside
`src/movie_review/eval/fixtures.py`, so the evaluators were scored against
a fixture that shipped with the code that consumed it: changing the module
silently changed the expected values, and the regression run could not
detect a change in the thing it was regressing.

The baseline is now a file under `tests/golden/`, and a test pins it to the
in-source fixture so the two cannot drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from movie_review.eval.fixtures import golden_analysis
from movie_review.eval.regression import run_regression

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden" / "golden-01"


def _load(name: str) -> Any:
    document = json.loads((GOLDEN / name).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_the_baseline_is_on_disk() -> None:
    """The directory was empty."""
    assert (GOLDEN / "analysis.json").is_file()
    assert (GOLDEN / "ground_truth.json").is_file()


def test_the_file_and_the_fixture_agree() -> None:
    """The fixture shipped with the code that consumed it.

    A change to `eval/fixtures.py` silently changed the values the
    evaluators were scored against. The two are now pinned together, so a
    change to either one has to be a deliberate change to both.
    """
    assert _load("analysis.json") == golden_analysis()


def test_the_baseline_passes_every_gate() -> None:
    """A known-good review passes plot accuracy, hallucination and coverage."""
    truth = _load("ground_truth.json")
    report = run_regression(
        truth["event_ids"],
        truth["event_ids"],
        truth["claims"],
        truth["evidence_ids"],
    )
    assert report.failures == [], report.failures
    assert report.passed is True
    assert report.plot_f1 == 1.0
    assert report.hallucination_rate == 0.0
    assert report.coverage == 100.0


def test_a_wrong_prediction_fails_the_baseline() -> None:
    """The baseline has to be able to fail, or it proves nothing."""
    truth = _load("ground_truth.json")
    report = run_regression(
        ["e_escape", "e_invented"],
        truth["event_ids"],
        truth["claims"],
        truth["evidence_ids"],
    )
    assert report.passed is False
    assert any("plot_f1" in failure for failure in report.failures)


def test_an_unsupported_major_claim_fails_the_baseline() -> None:
    """The hallucination gate has to bite."""
    truth = _load("ground_truth.json")
    claims = list(truth["claims"]) + [
        {
            "claim_id": "cl_bad",
            "text": "Ana dies in the harbour.",
            "type": "PLOT_FACT",
            "evidence": [],
            "verdict": "INSUFFICIENT_EVIDENCE",
        }
    ]
    report = run_regression(
        truth["event_ids"],
        truth["event_ids"],
        claims,
        truth["evidence_ids"],
    )
    assert report.passed is False
    assert any("hallucination" in failure for failure in report.failures)


def test_a_claim_without_evidence_fails_the_baseline() -> None:
    """The coverage gate has to bite."""
    truth = _load("ground_truth.json")
    claims = list(truth["claims"]) + [
        {
            "claim_id": "cl_uncovered",
            "text": "The harbour floods.",
            "type": "PLOT_FACT",
            "evidence": ["ev_does_not_exist"],
            "verdict": "SUPPORTED",
        }
    ]
    report = run_regression(
        truth["event_ids"],
        truth["event_ids"],
        claims,
        truth["evidence_ids"],
    )
    assert report.passed is False
    assert any("coverage" in failure for failure in report.failures)
