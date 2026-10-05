"""T080 acceptance: plot accuracy scores event-ID predictions."""

from movie_review.eval.accuracy import plot_accuracy


def test_plot_accuracy_perfect() -> None:
    result = plot_accuracy(["e_escape", "e_betrayal"], ["e_escape", "e_betrayal"])
    assert result.f1 == 1.0 and result.matched == 2


def test_plot_accuracy_partial() -> None:
    result = plot_accuracy(["e_escape", "e_nope"], ["e_escape", "e_betrayal"])
    assert result.precision == 0.5
    assert result.recall == 0.5
    assert result.matched == 1


def test_plot_accuracy_empty() -> None:
    assert plot_accuracy([], []).f1 == 1.0
    assert plot_accuracy([], ["e_escape"]).recall == 0.0
