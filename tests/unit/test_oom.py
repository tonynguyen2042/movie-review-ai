"""T071 acceptance: OOM classification and bounded recovery."""

import pytest

from movie_review.models.resources import (
    OOMRecoveryError,
    is_oom,
    run_with_oom_recovery,
)


def test_classify() -> None:
    assert is_oom(MemoryError("x")) is True
    assert is_oom(RuntimeError("CUDA out of memory")) is True
    assert is_oom(RuntimeError("mlx out of memory, tried 40GB")) is True
    assert is_oom(RuntimeError("Cannot allocate memory")) is True
    assert is_oom(RuntimeError("boom")) is False
    assert is_oom(ValueError("bad input")) is False


def test_recover_then_succeed() -> None:
    calls: list[str] = []
    unloads: list[str] = []

    def _flaky() -> str:
        calls.append("run")
        if len(calls) == 1:
            raise RuntimeError("out of memory")
        return "ok"

    assert run_with_oom_recovery(_flaky, lambda: unloads.append("unload")) == "ok"
    assert unloads == ["unload"]


def test_non_oom_propagates_without_unload() -> None:
    unloads: list[str] = []

    def _fails() -> None:
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        run_with_oom_recovery(_fails, lambda: unloads.append("unload"))
    assert unloads == []


def test_exhaustion_raises() -> None:
    calls: list[str] = []
    unloads: list[str] = []

    def _fails() -> None:
        calls.append("run")
        raise MemoryError("gone")

    with pytest.raises(MemoryError):
        run_with_oom_recovery(_fails, lambda: unloads.append("unload"), attempts=2)
    assert len(calls) == 2
    assert len(unloads) == 1


def test_unload_failure_wrapped() -> None:
    def _fails() -> None:
        raise MemoryError("gone")

    def _bad_unload() -> None:
        raise RuntimeError("stuck")

    with pytest.raises(OOMRecoveryError, match="Unload failed"):
        run_with_oom_recovery(_fails, _bad_unload)


def test_bad_attempts_rejected() -> None:
    with pytest.raises(ValueError, match="attempts"):
        run_with_oom_recovery(lambda: 1, lambda: None, attempts=0)
