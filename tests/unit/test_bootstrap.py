"""T001 acceptance: the package bootstraps on Python 3.12+."""

import sys

import movie_review


def test_package_importable() -> None:
    assert movie_review.__name__ == "movie_review"


def test_package_version() -> None:
    assert movie_review.__version__ == "0.1.0"


def test_python_minimum_version() -> None:
    assert sys.version_info >= (3, 12)
