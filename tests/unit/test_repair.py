"""T049 acceptance: verdict-driven script repair without prose invention."""

import pytest

from movie_review.domain import (
    Claim,
    ClaimStatus,
    ClaimType,
    ReviewParagraph,
    ReviewScript,
    ReviewSection,
)
from movie_review.review.factcheck import ClaimVerdict
from movie_review.review.repair import RepairError, repair_script


def _claim__repair(claim_id: str, type: ClaimType = ClaimType.PLOT_FACT) -> Claim:
    return Claim(claim_id=claim_id, text="Sarah knew about it.", type=type, evidence=["e1"])


def _script__repair() -> ReviewScript:
    return ReviewScript(
        sections=[
            ReviewSection(
                id="sec_01",
                type="hook",
                paragraphs=[
                    ReviewParagraph(
                        id="p1",
                        text="Sarah knew about it.",
                        target_seconds=12,
                        claims=[_claim__repair("c1"), _claim__repair("c2", ClaimType.OPINION)],
                        visual_intent="shot",
                    )
                ],
            )
        ]
    )


def _verdict(claim_id: str, status: ClaimStatus) -> ClaimVerdict:
    return ClaimVerdict(claim_id=claim_id, status=status, evidence=["e1"])


def test_supported_untouched() -> None:
    result = repair_script(_script__repair(), [_verdict("c1", ClaimStatus.SUPPORTED)])
    assert result.script.sections[0].paragraphs[0].claims[0].type is ClaimType.PLOT_FACT
    assert (result.removed, result.converted, result.qualified) == (0, 0, 0)


def test_contradicted_removed() -> None:
    result = repair_script(_script__repair(), [_verdict("c1", ClaimStatus.CONTRADICTED)])
    claims = result.script.sections[0].paragraphs[0].claims
    assert [c.claim_id for c in claims] == ["c2"]
    assert result.removed == 1


def test_insufficient_converted_to_interpretation() -> None:
    result = repair_script(_script__repair(), [_verdict("c1", ClaimStatus.INSUFFICIENT_EVIDENCE)])
    [converted, *_] = result.script.sections[0].paragraphs[0].claims
    assert converted.type is ClaimType.INTERPRETATION
    assert converted.evidence == []
    assert result.converted == 1


def test_insufficient_opinion_untouched() -> None:
    result = repair_script(_script__repair(), [_verdict("c2", ClaimStatus.INSUFFICIENT_EVIDENCE)])
    assert result.script.sections[0].paragraphs[0].claims[1].type is ClaimType.OPINION
    assert result.converted == 0


def test_partial_qualified() -> None:
    result = repair_script(_script__repair(), [_verdict("c1", ClaimStatus.PARTIALLY_SUPPORTED)])
    [qualified, *_] = result.script.sections[0].paragraphs[0].claims
    assert qualified.text == "Reportedly, sarah knew about it."
    assert result.qualified == 1


def test_unknown_verdict_rejected() -> None:
    with pytest.raises(RepairError, match="unknown claims"):
        repair_script(_script__repair(), [_verdict("ghost", ClaimStatus.SUPPORTED)])


def test_input_unmutated() -> None:
    script = _script__repair()
    before = script.model_dump_json()
    repair_script(script, [_verdict("c1", ClaimStatus.CONTRADICTED)])
    assert script.model_dump_json() == before
