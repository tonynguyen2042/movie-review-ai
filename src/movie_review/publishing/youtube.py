"""YouTube publishing adapter implementing :class:`PublishingPort` (T098).

Lazy, injected backend so tests and offline hosts never touch the network or
require the Google client libraries. The adapter does not invent metadata: it
uploads what :mod:`movie_review.publishing.metadata` produced.

Copyright (AGENTS.md): uploading is a user-initiated action. This adapter
makes no claim that any clip duration or percentage is legally safe, and it
never runs implicitly as part of the pipeline.
"""

from __future__ import annotations

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

# Valid YouTube privacy states.
PRIVACY_STATES = frozenset({"public", "unlisted", "private"})

DEFAULT_CATEGORY_ID = "22"  # Film & Animation


@dataclass(frozen=True)
class RawUpload:
    """Normalized payload handed to the platform client."""

    title: str
    description: str
    tags: list[str]
    video_path: Path
    thumbnail_path: Path | None
    privacy: str
    category_id: str


# Backend signature: takes a normalized payload, returns (video_id, url).
RawBackend = Callable[[RawUpload], tuple[str, str]]


def _load_youtube_backend() -> RawBackend:
    """Build the real YouTube backend or raise :class:`PublishingUnavailableError`.

    NOTE: the Google client call shape must be verified against the Data API v3
    on a credentialed host; offline and CI hosts always take the injected path.
    """
    try:
        from googleapiclient.discovery import build  # type: ignore[import-not-found]
        from googleapiclient.http import MediaFileUpload  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PublishingUnavailableError("google-api-python-client is not installed") from exc

    def _upload(payload: RawUpload) -> tuple[str, str]:
        service = build("youtube", "v3")
        request_body = {
            "snippet": {
                "title": payload.title,
                "description": payload.description,
                "tags": payload.tags,
                "categoryId": payload.category_id,
            },
            "status": {"privacyStatus": payload.privacy},
        }
        media = MediaFileUpload(str(payload.video_path))
        response = (
            service.videos()
            .insert(part="snippet,status", body=request_body, media_body=media)
            .execute()
        )
        video_id = str(response["id"])
        return video_id, f"https://www.youtube.com/watch?v={video_id}"

    return _upload


class YouTubeAdapter(PublishingPort):
    """YouTube Data API adapter (client injected or lazily loaded)."""

    def __init__(
        self,
        backend: RawBackend | None = None,
        category_id: str = DEFAULT_CATEGORY_ID,
    ) -> None:
        self._backend = backend
        self._category_id = category_id

    def _ensure_loaded(self) -> RawBackend:
        if self._backend is None:
            self._backend = _load_youtube_backend()
        return self._backend

    def available(self) -> bool:
        """True only when a backend can be obtained without raising."""
        try:
            self._ensure_loaded()
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

        if request.privacy not in PRIVACY_STATES:
            raise UploadRejectedError(f"Invalid privacy state: {request.privacy!r}")

        metadata = request.metadata
        if not metadata.title.strip():
            raise UploadRejectedError("Title must not be empty")

        thumbnail = request.thumbnail_path
        if thumbnail is not None and not Path(thumbnail).is_file():
            raise PublishingError(f"Thumbnail file does not exist: {thumbnail}")

        payload = RawUpload(
            title=metadata.title,
            description=metadata.description,
            tags=list(metadata.tags),
            video_path=video_path,
            thumbnail_path=Path(thumbnail) if thumbnail is not None else None,
            privacy=request.privacy,
            category_id=self._category_id,
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
