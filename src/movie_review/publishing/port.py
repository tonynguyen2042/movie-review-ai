"""Publishing port: platform-agnostic upload contract (T098, spec Phase 12).

Adapters (YouTube in T098, fakes in tests) implement :class:`PublishingPort`.
Domain and application code depend only on this contract, never on a
platform SDK. Automatic YouTube upload is out of core scope (spec section 5),
so this adapter is opt-in and never invoked implicitly by the pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class VideoMetadataLike(Protocol):
    """Structural contract the port needs from publishing metadata.

    Declared as a Protocol so the port stays independent of any concrete
    metadata model (:mod:`movie_review.publishing.metadata` satisfies it).
    """

    @property
    def title(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def tags(self) -> list[str]: ...


class PublishingError(Exception):
    """Base class for publishing failures."""


class PublishingUnavailableError(PublishingError):
    """The platform client or credentials cannot be loaded here."""

    def __init__(self, detail: str = "") -> None:
        message = "Publishing backend unavailable"
        if detail:
            message += f": {detail}"
        super().__init__(message)


class UploadRejectedError(PublishingError):
    """The platform refused the upload or its metadata."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Upload rejected: {reason}")
        self.reason = reason


@dataclass(frozen=True)
class UploadRequest:
    """One video plus its publishing metadata."""

    video_path: Path
    metadata: VideoMetadataLike
    thumbnail_path: Path | None = None
    privacy: str = "unlisted"


@dataclass(frozen=True)
class UploadReceipt:
    """Platform acknowledgement of an accepted upload."""

    video_id: str
    url: str
    status: str


class PublishingPort(ABC):
    """Video upload to a publishing platform."""

    @abstractmethod
    def upload(self, request: UploadRequest) -> UploadReceipt:
        """Upload one video; classified failures raise :class:`PublishingError`."""

    @abstractmethod
    def available(self) -> bool:
        """True when the adapter can upload here (credentials, SDK, network)."""
