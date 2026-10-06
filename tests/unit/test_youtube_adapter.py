"""T098 acceptance: YouTube publishing adapter over the publishing port."""

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from movie_review.publishing.port import (
    PublishingError,
    PublishingPort,
    PublishingUnavailableError,
    UploadReceipt,
    UploadRejectedError,
    UploadRequest,
    VideoMetadataLike,
)
from movie_review.publishing.youtube import (
    DEFAULT_CATEGORY_ID,
    PRIVACY_STATES,
    RawUpload,
    YouTubeAdapter,
)


@dataclass
class FakeMetadata:
    """Minimal object satisfying the structural metadata protocol."""

    title: str = "Blackrock Review"
    description: str = "A full plot breakdown."
    tags: list[str] = field(default_factory=lambda: ["thriller"])


def _video(tmp_path: Path) -> Path:
    path = tmp_path / "final.mp4"
    path.write_bytes(b"video-bytes")
    return path


def test_adapter_implements_port() -> None:
    """The adapter satisfies the publishing contract."""
    assert isinstance(YouTubeAdapter(backend=lambda p: ("id1", "url")), PublishingPort)


def test_metadata_protocol_accepts_concrete_object() -> None:
    """A duck-typed metadata object satisfies the port's protocol."""
    assert isinstance(FakeMetadata(), VideoMetadataLike)


def test_upload_returns_receipt(tmp_path: Path) -> None:
    """A successful upload returns the platform receipt."""
    seen: list[RawUpload] = []

    def backend(payload: RawUpload) -> tuple[str, str]:
        seen.append(payload)
        return "abc123", "https://www.youtube.com/watch?v=abc123"

    adapter = YouTubeAdapter(backend=backend)
    request = UploadRequest(video_path=_video(tmp_path), metadata=FakeMetadata())

    receipt = adapter.upload(request)

    assert isinstance(receipt, UploadReceipt)
    assert receipt.video_id == "abc123"
    assert receipt.status == "uploaded"
    assert len(seen) == 1


def test_upload_forwards_metadata_without_inventing(tmp_path: Path) -> None:
    """The adapter forwards exactly the metadata it was given."""
    captured: list[RawUpload] = []

    def backend(payload: RawUpload) -> tuple[str, str]:
        captured.append(payload)
        return "id", "url"

    metadata = FakeMetadata(title="Exact Title", description="Exact description.", tags=["a", "b"])
    adapter = YouTubeAdapter(backend=backend)
    adapter.upload(UploadRequest(video_path=_video(tmp_path), metadata=metadata))

    payload = captured[0]
    assert payload.title == "Exact Title"
    assert payload.description == "Exact description."
    assert payload.tags == ["a", "b"]
    assert payload.category_id == DEFAULT_CATEGORY_ID
    assert payload.privacy == "unlisted"


def test_upload_forwards_thumbnail_when_present(tmp_path: Path) -> None:
    """An existing thumbnail path is forwarded to the backend."""
    captured: list[RawUpload] = []

    def backend(payload: RawUpload) -> tuple[str, str]:
        captured.append(payload)
        return "id", "url"

    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"jpeg")

    adapter = YouTubeAdapter(backend=backend)
    adapter.upload(
        UploadRequest(
            video_path=_video(tmp_path),
            metadata=FakeMetadata(),
            thumbnail_path=thumb,
        )
    )
    assert captured[0].thumbnail_path == thumb


def test_upload_rejects_missing_video(tmp_path: Path) -> None:
    """A missing video file is rejected before the backend is called."""
    calls: list[RawUpload] = []
    adapter = YouTubeAdapter(backend=lambda p: (calls.append(p), ("id", "url"))[1])

    with pytest.raises(PublishingError):
        adapter.upload(UploadRequest(video_path=tmp_path / "absent.mp4", metadata=FakeMetadata()))
    assert calls == []


def test_upload_rejects_missing_thumbnail(tmp_path: Path) -> None:
    """A declared but absent thumbnail is a classified failure."""
    adapter = YouTubeAdapter(backend=lambda p: ("id", "url"))

    with pytest.raises(PublishingError):
        adapter.upload(
            UploadRequest(
                video_path=_video(tmp_path),
                metadata=FakeMetadata(),
                thumbnail_path=tmp_path / "absent.jpg",
            )
        )


@pytest.mark.parametrize("privacy", ["public", "unlisted", "private"])
def test_upload_accepts_valid_privacy(tmp_path: Path, privacy: str) -> None:
    """All documented privacy states are accepted."""
    adapter = YouTubeAdapter(backend=lambda p: ("id", "url"))
    receipt = adapter.upload(
        UploadRequest(video_path=_video(tmp_path), metadata=FakeMetadata(), privacy=privacy)
    )
    assert receipt.video_id == "id"


def test_upload_rejects_invalid_privacy(tmp_path: Path) -> None:
    """An unknown privacy state is rejected by the platform contract."""
    adapter = YouTubeAdapter(backend=lambda p: ("id", "url"))

    with pytest.raises(UploadRejectedError):
        adapter.upload(
            UploadRequest(video_path=_video(tmp_path), metadata=FakeMetadata(), privacy="secret")
        )


def test_privacy_states_are_exactly_documented() -> None:
    """The privacy set matches the platform's documented values."""
    assert PRIVACY_STATES == {"public", "unlisted", "private"}


def test_upload_rejects_empty_title(tmp_path: Path) -> None:
    """An empty title is rejected before upload."""
    adapter = YouTubeAdapter(backend=lambda p: ("id", "url"))

    with pytest.raises(UploadRejectedError):
        adapter.upload(
            UploadRequest(video_path=_video(tmp_path), metadata=FakeMetadata(title="   "))
        )


def test_upload_wraps_backend_failure(tmp_path: Path) -> None:
    """Backend exceptions become classified rejections."""

    def failing(payload: RawUpload) -> tuple[str, str]:
        raise RuntimeError("quota exceeded")

    adapter = YouTubeAdapter(backend=failing)

    with pytest.raises(UploadRejectedError):
        adapter.upload(UploadRequest(video_path=_video(tmp_path), metadata=FakeMetadata()))


def test_upload_rejects_empty_video_id(tmp_path: Path) -> None:
    """A blank platform id is rejected rather than reported as success."""
    adapter = YouTubeAdapter(backend=lambda p: ("", "url"))

    with pytest.raises(UploadRejectedError):
        adapter.upload(UploadRequest(video_path=_video(tmp_path), metadata=FakeMetadata()))


def test_available_true_with_injected_backend() -> None:
    """An injected backend means the adapter is usable."""
    assert YouTubeAdapter(backend=lambda p: ("id", "url")).available() is True


def test_available_false_when_backend_unavailable() -> None:
    """Without credentials/SDK the adapter reports unavailable, not an error."""
    adapter = YouTubeAdapter(backend=None)
    assert adapter.available() is False


def test_missing_backend_raises_unavailable(tmp_path: Path) -> None:
    """Attempting an upload with no backend raises the availability error."""
    adapter = YouTubeAdapter(backend=None)

    with pytest.raises(PublishingUnavailableError):
        adapter.upload(UploadRequest(video_path=_video(tmp_path), metadata=FakeMetadata()))
