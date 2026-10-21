"""T047 acceptance: deterministic verdicts for every status."""

import sqlite3
from pathlib import Path

from movie_review.domain import (
    Claim,
    ClaimStatus,
    ClaimType,
    Event,
    EventType,
    Job,
    TranscriptSegment,
)
from movie_review.review.factcheck import check_claim, check_claims
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


def _db(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(bootstrap(tmp_path / "f.db"))
    repo.save_job(conn, Job(job_id="job_1", input_file="m"))
    repo.save_transcript_segments(
        conn,
        "job_1",
        [
            TranscriptSegment(
                segment_id="seg_1", start=1.0, end=2.0, text="Sarah knew about the murder"
            )
        ],
    )
    repo.save_event(
        conn,
        "job_1",
        Event(
            id="event_00001",
            type=EventType.DISCOVERY,
            timestamp=50.0,
            description="Sarah knew about the murder.",
        ),
    )
    return conn


def _claim(text: str, type: ClaimType, evidence: list[str]) -> Claim:
    return Claim(claim_id="c1", text=text, type=type, evidence=evidence)


def test_supported(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    verdict = check_claim(
        _claim("Sarah knew about the murder.", ClaimType.PLOT_FACT, ["event_00001"]), conn, "job_1"
    )
    assert verdict.status is ClaimStatus.SUPPORTED
    conn.close()


def test_partially_supported(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    verdict = check_claim(
        _claim(
            "Sarah knew about the murder because the moon was bright and owls hooted loudly",
            ClaimType.PLOT_FACT,
            ["event_00001"],
        ),
        conn,
        "job_1",
    )
    assert verdict.status is ClaimStatus.PARTIALLY_SUPPORTED
    conn.close()


def test_insufficient_no_evidence(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    verdict = check_claim(_claim("Sarah knew.", ClaimType.PLOT_FACT, []), conn, "job_1")
    assert verdict.status is ClaimStatus.INSUFFICIENT_EVIDENCE
    conn.close()


def test_insufficient_dangling_and_zero_coverage(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    dangling = check_claim(_claim("Sarah knew.", ClaimType.PLOT_FACT, ["ghost"]), conn, "job_1")
    assert dangling.status is ClaimStatus.INSUFFICIENT_EVIDENCE
    zero = check_claim(
        _claim("Spaceships orbit Mars.", ClaimType.PLOT_FACT, ["event_00001"]), conn, "job_1"
    )
    assert zero.status is ClaimStatus.INSUFFICIENT_EVIDENCE
    conn.close()


def test_contradicted_misquote(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    verdict = check_claim(
        _claim('Sarah said "goodbye forever".', ClaimType.DIALOGUE_REFERENCE, ["seg_1"]),
        conn,
        "job_1",
    )
    assert verdict.status is ClaimStatus.CONTRADICTED
    quoted = check_claim(
        _claim('Sarah said "knew about the murder".', ClaimType.DIALOGUE_REFERENCE, ["seg_1"]),
        conn,
        "job_1",
    )
    assert quoted.status is not ClaimStatus.CONTRADICTED
    conn.close()


def test_one_fabricated_quote_among_several_is_contradicted(tmp_path: Path) -> None:
    """Regression: a partly invented quotation was judged clean.

    The rule is that a quote is misquoted when it appears in none of the
    cited segments. Asking instead whether *any* quote matched *any* segment
    meant a claim quoting two lines passed as long as one of them was real --
    which is the shape an invented line takes.
    """
    conn = _db(tmp_path)
    verdict = check_claim(
        _claim(
            'Sarah said "knew about the murder" and then "goodbye forever".',
            ClaimType.DIALOGUE_REFERENCE,
            ["seg_1"],
        ),
        conn,
        "job_1",
    )
    assert verdict.status is ClaimStatus.CONTRADICTED
    conn.close()


def test_several_real_quotes_are_not_contradicted(tmp_path: Path) -> None:
    """Several genuine quotations in one claim are still supported."""
    conn = _db(tmp_path)
    repo.save_transcript_segments(
        conn,
        "job_1",
        [
            TranscriptSegment(
                segment_id="seg_2", start=3.0, end=4.0, text="The photograph was in the drawer"
            )
        ],
    )
    verdict = check_claim(
        _claim(
            'Sarah said "knew about the murder" and "the photograph was in the drawer".',
            ClaimType.DIALOGUE_REFERENCE,
            ["seg_1", "seg_2"],
        ),
        conn,
        "job_1",
    )
    assert verdict.status is not ClaimStatus.CONTRADICTED
    conn.close()


def test_non_factual_supported(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    verdict = check_claim(_claim("This is a masterpiece.", ClaimType.OPINION, []), conn, "job_1")
    assert verdict.status is ClaimStatus.SUPPORTED
    conn.close()


def test_check_claims_order(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    verdicts = check_claims(
        [
            _claim("Sarah knew.", ClaimType.PLOT_FACT, ["event_00001"]),
            _claim("Great film.", ClaimType.OPINION, []),
        ],
        conn,
        "job_1",
    )
    assert [v.claim_id for v in verdicts] == ["c1", "c1"]
    conn.close()
