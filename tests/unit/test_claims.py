"""T045 acceptance: claim validation, IDs, and persistence."""

from pathlib import Path

import pytest

from movie_review.domain import (
    Claim,
    ClaimStatus,
    Job,
    ReviewParagraph,
    ReviewScript,
    ReviewSection,
)
from movie_review.review.claims import ClaimExtractionError, extract_claims, store_claims
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect
from tests.helpers import (
    _claim,
)


def _paragraph__claims(paragraph_id: str, *claims: Claim) -> ReviewParagraph:
    return ReviewParagraph(
        id=paragraph_id,
        text="Some narration here.",
        target_seconds=12,
        claims=list(claims),
        visual_intent="shot",
    )


def _script__claims() -> ReviewScript:
    return ReviewScript(
        sections=[
            ReviewSection(
                id="sec_01", type="hook", paragraphs=[_paragraph__claims("p1", _claim("c1"))]
            ),
            ReviewSection(
                id="sec_02",
                type="climax",
                paragraphs=[_paragraph__claims("p2", _claim("c2"), _claim("c3", "John fled."))],
            ),
        ]
    )


def test_extract_preserves_order_and_ids() -> None:
    claims = extract_claims(_script__claims())
    assert [c.claim_id for c in claims] == ["c1", "c2", "c3"]
    assert all(c.status is ClaimStatus.INSUFFICIENT_EVIDENCE for c in claims)
    assert claims[2].text == "John fled."


def test_duplicate_ids_rejected() -> None:
    script = _script__claims()
    script.sections[1].paragraphs[0].claims.append(_claim("c1"))
    with pytest.raises(ClaimExtractionError, match="Duplicate claim ID"):
        extract_claims(script)


def test_empty_text_rejected() -> None:
    script = _script__claims()
    script.sections[0].paragraphs[0].claims[0].text = "   "
    with pytest.raises(ClaimExtractionError, match="Empty claim text"):
        extract_claims(script)


def test_missing_id_gets_fallback() -> None:
    script = _script__claims()
    script.sections[0].paragraphs[0].claims[0].claim_id = ""
    [first, *_] = extract_claims(script)
    assert first.claim_id == "p1-c1"


def test_store_round_trip(tmp_path: Path) -> None:
    conn = connect(bootstrap(tmp_path / "c.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    claims = extract_claims(_script__claims())
    store_claims(conn, "job_1", claims)
    stored = repo.list_claims(conn, "job_1")
    assert [c.claim_id for c in stored] == ["c1", "c2", "c3"]
    conn.close()
