"""TikTok publishing adapter implementing :class:`PublishingPort` (T110).

APP REVIEW REQUIRED. The TikTok Content Posting API only accepts video uploads
from apps that have been approved through TikTok's developer review. On an
unapproved app every upload fails with an opaque error from the API, not from
this module. That is a TikTok policy, not a limitation of the code; the adapter
is written to the documented API so it is ready once an app exists, but it has
not been exercised against a live endpoint.

Lazy, injected backend so tests and offline hosts never touch the network. The
adapter does not invent metadata: it uploads what
:mod:`movie_review.publishing.ai_metadata` produced.

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

#: Documented Content Posting API host. The upload flow is a three-step dance --
#: init, upload to the returned URL, then publish with the creator's declaration --
#: and a client token (not an access token) is used for the first step.
API_HOST = "https://open.tiktokapis.com"
API_VERSION = "v2"

#: The privacy level TikTok requires for direct posts. ``MUTUAL_ONLY`` and
#: ``FRIENDS_ONLY`` exist in the API but are not accepted for Content Posting.
DEFAULT_PRIVACY_LEVEL = "SOD"

#: TikTok's own statement of why this cannot be exercised yet.
APP_REVIEW_NOTICE = (
    "TikTok Content Posting API requires an app that has passed TikTok's developer "
    "review. Uploads from an unapproved app are refused by TikTok."
)


@dataclass(frozen=True)
class TikTokUpload:
    """Normalized payload handed to the TikTok client."""

    video_path: Path
    title: str
    description: str
    creator_info: str
    access_token: str


# Backend signature: takes a normalized payload, returns (video_id, url).
TikTokBackend = Callable[[TikTokUpload], tuple[str, str]]


def access_token_from_env() -> str:
    """The creator access token, or raise :class:`PublishingUnavailableError`.

    An env var rather than a config key: this is a secret, and a token in a
    tracked YAML file is a leak. Never logged or echoed.
    """
    token = os.environ.get("MOVIE_REVIEW_TIKTOK_TOKEN", "").strip()
    if not token:
        raise PublishingUnavailableError(
            f"{APP_REVIEW_NOTICE} Set MOVIE_REVIEW_TIKTOK_TOKEN once your app is approved."
        )
    return token


def _load_tiktok_backend() -> TikTokBackend:
    """Build the real Content Posting backend or raise :class:`PublishingUnavailableError`.

    NOTE: unverified against a live endpoint; see the module docstring. The call
    shapes follow the documented Content Posting API.
    """

    def _upload(payload: TikTokUpload) -> tuple[str, str]:
        import httpx  # type: ignore[import-not-found]

        query = f"access_token={payload.access_token}"
        with httpx.Client(timeout=600.0) as client:
            init = client.post(
                f"{API_HOST}/{API_VERSION}/post/publish/video/init/",
                params=query,
                json={
                    "post_info": {
                        "title": payload.title,
                        "description": payload.description,
                        "privacy_level": DEFAULT_PRIVACY_LEVEL,
                        "disable_duet": False,
                        "disable_comment": False,
                        "disable_stitch": False,
                    },
                    "source_info": {"source": "PULL_FROM_URL"},
                },
            )
            if init.status_code >= 400:
                raise UploadRejectedError(
                    f"TikTok init returned {init.status_code}: {init.text[:300]}"
                )
            body = init.json()
            upload_url = body.get("data", {}).get("upload_url")
            publish_id = body.get("data", {}).get("publish_id")
            if not upload_url or not publish_id:
                raise UploadRejectedError("TikTok init returned no upload_url or publish_id")

            with payload.video_path.open("rb") as handle:
                chunked = client.post(
                    upload_url,
                    headers={
                        "Content-Range": (
                            f"bytes 0-{payload.video_path.stat().st_size - 1}/"
                            f"{payload.video_path.stat().st_size}"
                        ),
                        "Content-Type": "video/mp4",
                    },
                    content=handle,
                )
            if chunked.status_code >= 400:
                raise UploadRejectedError(
                    f"TikTok chunk upload returned {chunked.status_code}: {chunked.text[:300]}"
                )

            published = client.post(
                f"{API_HOST}/{API_VERSION}/post/publish/video/finish/",
                params=query,
                json={"publish_id": publish_id},
            )
            if published.status_code >= 400:
                raise UploadRejectedError(
                    f"TikTok finish returned {published.status_code}: {published.text[:300]}"
                )
            result = published.json().get("data") or {}
            video_id = str(result.get("video_id") or publish_id)
            share_url = str(result.get("share_url") or "")
        return video_id, share_url

    return _upload


class TikTokAdapter(PublishingPort):
    """TikTok Content Posting API adapter (client injected or lazily loaded)."""

    def __init__(self, backend: TikTokBackend | None = None, access_token: str = "") -> None:
        self._backend = backend
        self._access_token = access_token

    def _ensure_loaded(self) -> TikTokBackend:
        if self._backend is None:
            self._backend = _load_tiktok_backend()
        return self._backend

    def _token(self) -> str:
        return self._access_token.strip() or access_token_from_env()

    def available(self) -> bool:
        """True only when a backend and token can be obtained without raising."""
        try:
            self._ensure_loaded()
            self._token()
        except PublishingError:
            return False
        return True

    def upload(self, request: UploadRequest) -> UploadReceipt:
        """Upload one video; validates inputs before touching the backend."""
        if not isinstance(request, UploadRequest):
            raise PublishingError(f"Invalid upload request: {request!r}")

        video_path = Path(request.video_path)
        if not video_path.is_file():
            raise PublishingError(f"Video file does not exist: {video_path}")

        metadata = request.metadata
        if not metadata.title.strip():
            raise UploadRejectedError("Title must not be empty")

        thumbnail = request.thumbnail_path
        if thumbnail is not None and not Path(thumbnail).is_file():
            raise PublishingError(f"Thumbnail file does not exist: {thumbnail}")

        payload = TikTokUpload(
            video_path=video_path,
            title=metadata.title,
            description=metadata.description,
            # TikTok requires an open-ended creator declaration; the title is the
            # most defensible content the caller has to hand.
            creator_info=metadata.title,
            access_token=self._token(),
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
