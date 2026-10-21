"""The published title must not carry the operator's directory layout.

T124 regression. The publish command derived the movie title by splitting the
path on "/" alone. A Windows path contains no forward slash, so
`D:\\Movies\\film.mkv` produced the title `D:\\Movies\\film` -- which was sent
to the model and embedded in the published YouTube, Facebook and TikTok
metadata.
"""

from __future__ import annotations

from movie_review.cli.app import _movie_title


def test_a_posix_path_yields_the_stem() -> None:
    assert _movie_title("/home/op/movies/film.mkv") == "film"


def test_a_windows_path_yields_the_stem() -> None:
    assert _movie_title(r"D:\Movies\film.mkv") == "film"


def test_a_windows_unc_path_yields_the_stem() -> None:
    assert _movie_title(r"\\nas\share\film.mkv") == "film"


def test_a_relative_path_yields_the_stem() -> None:
    assert _movie_title("movies/film.mkv") == "film"


def test_a_bare_name_yields_itself() -> None:
    assert _movie_title("film.mkv") == "film"


def test_the_title_never_contains_a_separator() -> None:
    for raw in (
        "/home/op/movies/film.mkv",
        r"D:\Movies\film.mkv",
        r"\\nas\share\film.mkv",
        "movies/film.mkv",
    ):
        title = _movie_title(raw)
        assert "/" not in title
        assert "\\" not in title
