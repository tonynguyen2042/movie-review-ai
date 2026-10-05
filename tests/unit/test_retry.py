"""T070 acceptance: bounded retries with classified errors."""

import pytest

from movie_review.pipeline.retry import RetryPolicy, run_with_retry


def test_success_first_try() -> None:
    result = run_with_retry(lambda: 42)
    assert (result.value, result.attempts) == (42, 1)


def test_flaky_then_success() -> None:
    calls: list[int] = []

    def _flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("transient")
        return "ok"

    result = run_with_retry(_flaky)
    assert (result.value, result.attempts) == ("ok", 3)


def test_exhaustion_raises_last() -> None:
    calls: list[int] = []

    def _fails() -> None:
        calls.append(1)
        raise RuntimeError(f"boom {len(calls)}")

    with pytest.raises(RuntimeError, match="boom 2"):
        run_with_retry(_fails, RetryPolicy(max_attempts=2))
    assert len(calls) == 2


def test_non_retryable_propagates_immediately() -> None:
    calls: list[int] = []

    def _fails() -> None:
        calls.append(1)
        raise TypeError("fatal")

    with pytest.raises(TypeError):
        run_with_retry(_fails, RetryPolicy(retry_on=(ValueError,)))
    assert len(calls) == 1


def test_bad_policy_rejected() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError, match="backoff"):
        RetryPolicy(backoff_seconds=-1.0)
