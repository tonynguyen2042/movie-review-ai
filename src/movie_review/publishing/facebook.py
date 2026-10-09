"""Facebook Page publishing adapter implementing :class:`PublishingPort` (T110).

Page video only. Reels and Groups are deliberately absent: Reels needs a
vertical 9:16 asset and Groups have a different permission and moderation model,
so supporting them here would mean this adapter silently mishandled them.

Lazy, injected backend so tests and offline hosts never touch the network and
never require the Facebook SDK. The adapter does not invent metadata: it uploads
what :mod:`movie_review.publishing.ai_metadata` produced.

Copyright (AGENTS.md): uploading is a user-initiated action. This adapter makes no
claim that any clip duration or percentage is legally safe, and it never runs
implicitly as part of the pipeline.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from movie_review.publishing.port import (
    PublishingError,
    PublishingPort,
    PublishingUnavailableError,
    UploadReceipt,
    UploadRejectedError,
    UploadRequest,
)

#: Graph API version this adapter targets. Pinned rather than "latest" so a
#: Graph change cannot silently alter a payload shape between runs.
GRAPH_API_VERSION = "v21.0"

#: Facebook Page videos are public or not uploaded at all. There is no per-video
#: privacy field on the Graph endpoint -- audience is a Page-level setting -- so
#: this adapter accepts only the value that matches that reality rather than
#: accepting "unlisted" or "private" and quietly ignoring them.
VISIBILITIES = frozenset({"public"})
DEFAULT_VISIBILITY = "public"

#: What a caller asks for when the pipeline's default (unlisted, correct for
#: YouTube) means nothing here.
UNSUPPORTED_VISIBILITY_HINT = (
    "Facebook Page videos cannot be published unlisted or private per upload; "
    "audience is controlled by the Page. Set the Page's audience, or upload as "
    "public. Nothing was sent."
)


@dataclass(frozen=True)
class PageUpload:
    """Normalized payload handed to the Facebook client."""

    page_id: str
    title: str
    description: str
    video_path: Path
    visibility: str
    access_token: str


# Backend signature: takes a normalized payload, returns (video_id, url).
PageBackend = Callable[[PageUpload], tuple[str, str]]


def access_token_from_env() -> str:
    """The Page access token, or raise :class:`PublishingUnavailableError`.

    An env var rather than a config key: this is a secret, and a token in a
    tracked YAML file is a leak. Never logged or echoed.
    """
    token = os.environ.get("MOVIE_REVIEW_FACEBOOK_TOKEN", "").strip()
    if not token:
        raise PublishingUnavailableError(
            "MOVIE_REVIEW_FACEBOOK_TOKEN is not set; a Page access token is required"
        )
    return token


def _load_page_backend() -> PageBackend:
    """Build the real Graph API backend or raise :class:`PublishingUnavailableError`.

    NOTE: the Graph call shape must be verified against a credentialed Page; an
    offline or CI host always takes the injected path.
    """

    def _upload(payload: PageUpload) -> tuple[str, str]:
        import httpx  # type: ignore[import-not-found]

        url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{payload.page_id}/videos"
        with httpx.Client(timeout=600.0) as client:
            with payload.video_path.open("rb") as handle:
                response = client.post(
                    url,
                    data={
                        "description": payload.description,
                        "title": payload.title,
                        "access_token": payload.access_token,
                    },
                    files={"source": (payload.video_path.name, handle, "video/mp4")},
                )
        if response.status_code >= 400:
            raise UploadRejectedError(
                f"Graph API returned {response.status_code}: {response.text[:300]}"
            )
        body = response.json()
        video_id = str(body.get("id") or "")
        return video_id, f"https://www.facebook.com/{video_id}" if video_id else ""

    return _upload


class FacebookPageAdapter(PublishingPort):
    """Facebook Graph API adapter for Page video (client injected or lazily loaded)."""

    def __init__(
        self,
        backend: PageBackend | None = None,
        page_id: str = "",
        access_token: str = "",
    ) -> None:
        self._backend = backend
        self._page_id = page_id
        self._access_token = access_token

    def _ensure_loaded(self) -> PageBackend:
        if self._backend is None:
            self._backend = _load_page_backend()
        return self._backend

    def _credentials(self) -> tuple[str, str]:
        """Page id and token, or raise :class:`PublishingUnavailableError`."""
        page_id = (
            self._page_id.strip() or os.environ.get("MOVIE_REVIEW_FACEBOOK_PAGE_ID", "").strip()
        )
        if not page_id:
            raise PublishingUnavailableError(
                "MOVIE_REVIEW_FACEBOOK_PAGE_ID is not set; a Page id is required"
            )
        token = self._access_token.strip() or access_token_from_env()
        return page_id, token

    def available(self) -> bool:
        """True only when a backend and credentials can be obtained without raising."""
        try:
            self._ensure_loaded()
            self._credentials()
        except PublishingError:
            return False
        return True

    def upload(self, request: UploadRequest) -> UploadReceipt:
        """Upload one video to a Page; validates inputs before touching the backend."""
        if not isinstance(request, UploadRequest):
            raise PublishingError(f"Invalid upload request: {request!r}")

        video_path = Path(request.video_path)
        if not video_path.is_file():
            raise PublishingError(f"Video file does not exist: {video_path}")

        visibility = request.privacy
        if visibility not in VISIBILITIES:
            raise UploadRejectedError(f"{UNSUPPORTED_VISIBILITY_HINT} (got {visibility!r})")

        metadata = request.metadata
        if not metadata.title.strip():
            raise UploadRejectedError("Title must not be empty")

        thumbnail = request.thumbnail_path
        if thumbnail is not None and not Path(thumbnail).is_file():
            raise PublishingError(f"Thumbnail file does not exist: {thumbnail}")

        page_id, token = self._credentials()
        payload = PageUpload(
            page_id=page_id,
            title=metadata.title,
            description=metadata.description,
            video_path=video_path,
            visibility=visibility,
            access_token=token,
        )

        try:
            video_id, url = self._ensure_loaded()(payload)
        except PublishingError:
            raise
        except Exception as exc:
            raise UploadRejectedError(str(exc)) from exc

        if not video_id:
            raise UploadRejectedError("Platform returned an empty video id")

        return UploadReceipt(video_id=video_id, url=url, status="uploaded")
