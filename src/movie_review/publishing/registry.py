"""Platform registry for publishing (T110).

Maps a platform name to its adapter so the CLI never names a concrete adapter and
adding a platform does not mean editing the command. Adapters are constructed
lazily: building one is cheap, but constructing the *backend* is not, and an
unavailable platform must not raise at import time.

Facebook and TikTok are present but their backends are unverified against live
endpoints -- see their modules. ``available()`` is the honest question to ask
before promising an upload will work.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from movie_review.publishing.port import PublishingPort

#: Platform name -> zero-argument adapter constructor.
AdapterFactory = Callable[[], PublishingPort]

PLATFORMS: dict[str, AdapterFactory] = {}


def _youtube() -> PublishingPort:
    from movie_review.publishing.youtube import YouTubeAdapter

    return YouTubeAdapter()


def _facebook() -> PublishingPort:
    from movie_review.publishing.facebook import FacebookPageAdapter

    return FacebookPageAdapter()


def _tiktok() -> PublishingPort:
    from movie_review.publishing.tiktok import TikTokAdapter

    return TikTokAdapter()


PLATFORMS = {
    "youtube": _youtube,
    "facebook": _facebook,
    "tiktok": _tiktok,
}


def platform_names() -> list[str]:
    """Supported platform names, sorted."""
    return sorted(PLATFORMS)


def is_platform(name: str) -> bool:
    """True when ``name`` is a supported platform."""
    return name.strip().lower() in PLATFORMS


def build_adapter(name: str) -> PublishingPort:
    """Build the adapter for ``name``.

    Raises:
        KeyError: if the platform is not supported.
    """
    key = name.strip().lower()
    try:
        factory = PLATFORMS[key]
    except KeyError as exc:
        raise KeyError(f"Unknown platform {name!r}; expected one of {platform_names()}") from exc
    return factory()


def unavailable_reason(name: str, adapter: PublishingPort) -> str:
    """Why this adapter cannot upload here, for a message an operator can act on.

    Constructed from the platform's own requirement rather than a generic
    "unavailable", because the action differs: a missing env var is fixed by
    setting it; an unapproved TikTok app is not.
    """
    from movie_review.publishing.facebook import UNSUPPORTED_VISIBILITY_HINT
    from movie_review.publishing.tiktok import APP_REVIEW_NOTICE

    key = name.strip().lower()
    if key == "facebook":
        if not os.environ.get("MOVIE_REVIEW_FACEBOOK_PAGE_ID", "").strip():
            return "MOVIE_REVIEW_FACEBOOK_PAGE_ID is not set."
        if not os.environ.get("MOVIE_REVIEW_FACEBOOK_TOKEN", "").strip():
            return "MOVIE_REVIEW_FACEBOOK_TOKEN is not set."
        return UNSUPPORTED_VISIBILITY_HINT
    if key == "tiktok":
        if not os.environ.get("MOVIE_REVIEW_TIKTOK_TOKEN", "").strip():
            return APP_REVIEW_NOTICE
        return "TikTok credentials are present but the app must have passed developer review."

    if adapter.available():
        return ""
    return "No publishing backend could be loaded on this host."
