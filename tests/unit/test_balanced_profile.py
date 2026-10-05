"""T077 acceptance: balanced profile contract matches default settings."""

from movie_review.config.profiles import validate_balanced_profile
from movie_review.config.settings import load_settings


def test_balanced_profile_is_default() -> None:
    validate_balanced_profile(load_settings())
