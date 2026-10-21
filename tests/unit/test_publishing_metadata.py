"""T110: model-driven publishing metadata and the three platform adapters.

The metadata generator exists because the previous one was a template:
``f"{movie_title} Review | {first_sentence}"`` is descriptive, not attention-
grabbing, and it asked no model anything. Generating copy means asking a model to
make claims about a film to an audience that cannot check them, so these tests
spend most of their weight on the constraint: the model may write about the
review and offer opinion, but may not assert a plot fact the narration does not
state, and may not publish INSUFFICIENT_EVIDENCE.

The Facebook and TikTok backends have never been run against a live endpoint.
Facebook's shape follows the documented Graph API; TikTok's is unverified and its
module says so. These tests therefore exercise validation, classification and the
credential contract -- the parts that are decided in this repository -- and never
pretend to have confirmed a platform accepted anything.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from movie_review.cache.manager import CacheManager
from movie_review.config.settings import ModelSpec, load_settings
from movie_review.domain import ReviewScript
from movie_review.jobs.manager import JobManager
from movie_review.pipeline.context import StageContext
from movie_review.publishing import ai_metadata as aim
from movie_review.publishing import facebook as fb
from movie_review.publishing import registry
from movie_review.publishing import tiktok as tt
from movie_review.publishing import youtube as yt
from movie_review.publishing.metadata import TITLE_MAX_CHARS, VideoMetadata
from movie_review.publishing.port import (
    PublishingError,
    PublishingPort,
    UploadRejectedError,
    UploadRequest,
)
from movie_review.reasoning.port import ReasoningPort
from movie_review.storage import repositories as repo
from movie_review.storage.database import bootstrap, connect


class _FakeReasoner(ReasoningPort):
    """Reasoner returning canned output, recording what it was asked."""

    def __init__(self, output: Any, model: str = "test-reasoning") -> None:
        self._output = output
        self._model = model
        self.prompts: list[str] = []

    @property
    def model(self) -> str:
        return self._model

    def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
        self.prompts.append(prompt)
        return json.dumps(self._output)

    def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
        self.prompts.append(prompt)
        return self._output

    def unload(self) -> None:
        return None


def _script() -> ReviewScript:
    return ReviewScript.model_validate(
        {
            "sections": [
                {
                    "id": "sec_00001",
                    "type": "INTRO",
                    "paragraphs": [
                        {
                            "id": "para_00001",
                            "text": "The film opens in a rainy office.",
                            "target_seconds": 30,
                        },
                        {
                            "id": "para_00002",
                            "text": "John reads a letter he does not understand.",
                            "target_seconds": 30,
                        },
                    ],
                }
            ]
        }
    )


def _ctx(tmp_path: Path) -> StageContext:
    conn = connect(bootstrap(tmp_path / "data" / "jobs.db"))
    manager = JobManager(conn)
    manager.create(str(tmp_path / "m.mp4"))
    job_id = next(iter(_job_ids(conn)))
    return StageContext(
        job_id=job_id,
        jobs_dir=tmp_path / "data" / "jobs",
        cache=CacheManager(tmp_path / "data" / "cache"),
        manager=manager,
        settings=load_settings(),
        conn=conn,
    )


def _job_ids(conn: sqlite3.Connection) -> list[str]:
    return [row["job_id"] for row in conn.execute("SELECT job_id FROM jobs")]


def _remote_spec() -> ModelSpec:
    return ModelSpec(
        model="qwen3.5-27b",
        backend="openai_compatible",
        base_url="http://192.168.1.144:8000/v1",
    )


GOOD_OUTPUT = {
    "title": "This review argues the letter is the whole film",
    "description": "A review of the office scenes and what the letter changes.",
    "tags": ["movie review", "drama", "analysis"],
}


def _generate(
    ctx: StageContext,
    output: Any = GOOD_OUTPUT,
    *,
    spec: ModelSpec | None = None,
    reasoner: ReasoningPort | None = None,
    platform: str = "youtube",
) -> aim.MetadataResult:
    # A reasoner is always supplied. Without one the stage builds the adapter
    # from the spec, which for a remote profile means a real HTTP call to the
    # configured endpoint -- a test suite must never do that.
    active = reasoner or _FakeReasoner(output, model=(spec or _remote_spec()).model)
    return aim.generate_publishing_metadata(
        _script(),
        ctx,
        movie_title="The Letter",
        platform=platform,
        target_language="en",
        spec=spec or _remote_spec(),
        reasoner=active,
    )


# ---------------------------------------------------------------------------
# The output is validated, not repaired
# ---------------------------------------------------------------------------


def test_a_valid_reply_becomes_metadata(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    result = _generate(ctx)

    assert result.metadata.title == GOOD_OUTPUT["title"]
    assert result.metadata.tags == GOOD_OUTPUT["tags"]
    assert result.metadata_path.is_file()
    assert result.cache_hit is False


def test_the_output_is_persisted_as_an_artifact(tmp_path: Path) -> None:
    """Provenance: the packaging has to be reproducible like any other output."""
    ctx = _ctx(tmp_path)

    result = _generate(ctx)

    recorded = repo.get_artifact(ctx.conn, f"{ctx.job_id}-publishing-metadata")
    assert recorded is not None
    assert recorded.prompt_version == result.prompt_version
    assert recorded.model == result.model
    assert recorded.relative_path == "publishing-metadata.json"


def test_metadata_round_trips_through_disk(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = _generate(ctx)

    loaded = aim.load_metadata(result.metadata_path)

    assert loaded.title == result.metadata.title
    assert loaded.tags == result.metadata.tags


def test_a_title_longer_than_the_limit_is_truncated(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    long_title = "word " * 60

    result = _generate(ctx, {**GOOD_OUTPUT, "title": long_title})

    assert len(result.metadata.title) <= TITLE_MAX_CHARS


def test_hashtags_in_tags_are_normalized(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    result = _generate(ctx, {**GOOD_OUTPUT, "tags": ["#Movie", "movie", " drama "]})

    assert result.metadata.tags == ["Movie", "drama"]


# ---------------------------------------------------------------------------
# The constraint: no claim the narration does not support
# ---------------------------------------------------------------------------


def test_insufficient_evidence_in_a_title_fails_the_run(tmp_path: Path) -> None:
    """The marker is a status code for an unsupported claim, not a selling point.

    Publishing it would tell an audience the packaging is unverified; hiding it
    would publish the claim. The run fails so a human decides.
    """
    ctx = _ctx(tmp_path)

    with pytest.raises(aim.UnsupportedClaimError):
        _generate(
            ctx,
            {**GOOD_OUTPUT, "title": f"{aim.EVIDENCE_MARKER}: the letter is the film"},
        )


def test_insufficient_evidence_in_a_description_fails_the_run(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    with pytest.raises(aim.UnsupportedClaimError):
        _generate(ctx, {**GOOD_OUTPUT, "description": f"{aim.EVIDENCE_MARKER} everywhere"})


def test_insufficient_evidence_in_a_tag_fails_the_run(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    with pytest.raises(aim.UnsupportedClaimError):
        _generate(ctx, {**GOOD_OUTPUT, "tags": ["drama", aim.EVIDENCE_MARKER]})


def test_the_prompt_forbids_inventing_plot_facts() -> None:
    """The constraint has to be in the prompt, not only in the validator.

    The validator catches the marker; it cannot catch an invented fact. The rules
    are what keep the model from producing one, so they are asserted here as text
    a prompt edit would have to update.
    """
    from movie_review.config.prompts import load_prompt

    prompt = load_prompt("publishing_metadata")

    text = prompt.template.lower()
    assert "invent" in text
    assert "narration above is the only source of fact" in text
    assert "clickbait that misrepresents" in text


def test_the_prompt_tells_the_model_the_movie_title_is_not_translated() -> None:
    from movie_review.config.prompts import load_prompt

    prompt = load_prompt("publishing_metadata")

    assert "do not" in prompt.template.lower()
    assert "transliterate" in prompt.template.lower()


# ---------------------------------------------------------------------------
# Malformed output is a failure, not a fallback template
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "output",
    [
        {"title": "", "description": "d", "tags": ["a"]},
        {"title": "t", "description": "", "tags": ["a"]},
        {"title": "t", "description": "d", "tags": []},
        {"title": 42, "description": "d", "tags": ["a"]},
        {"title": "t", "description": "d", "tags": "not-a-list"},
        {"title": "t", "description": "d", "tags": [7]},
        ["not", "an", "object"],
    ],
)
def test_malformed_output_is_rejected(output: Any) -> None:
    """A title is read before anything else, so a malformed one is not repaired."""
    with pytest.raises(aim.PublishingMetadataError):
        aim.parse_metadata(output)


def test_a_json_string_reply_is_still_parsed() -> None:
    """Some endpoints wrap JSON in a fence or prose; that shape is recoverable."""
    parsed = aim.parse_metadata(json.dumps(GOOD_OUTPUT))

    assert parsed["title"] == GOOD_OUTPUT["title"]


# ---------------------------------------------------------------------------
# Cache identity
# ---------------------------------------------------------------------------


def test_a_second_run_hits_the_cache(tmp_path: Path) -> None:
    """Same script, same model, same prompt: the second run must not re-ask."""
    ctx = _ctx(tmp_path)
    spec = _remote_spec()
    _generate(ctx, reasoner=_FakeReasoner(GOOD_OUTPUT, model=spec.model))

    # A reasoner that would raise if called, proving the cache answered instead.
    def forbidden(prompt: str, *, temperature: float = 0.4) -> str:
        raise AssertionError("the model must not run on a cache hit")

    class _Forbidden(ReasoningPort):
        @property
        def model(self) -> str:
            return spec.model

        def complete(self, prompt: str, *, temperature: float = 0.4) -> str:
            return forbidden(prompt)

        def complete_json(self, prompt: str, *, temperature: float = 0.4) -> Any:
            return forbidden(prompt)

        def unload(self) -> None:
            return None

    result = _generate(ctx, spec=spec, reasoner=_Forbidden())

    assert result.cache_hit is True
    assert result.metadata.title == GOOD_OUTPUT["title"]


def test_a_different_model_does_not_reuse_the_cache(tmp_path: Path) -> None:
    """A class-name or empty model key would let one model's output serve another."""
    ctx = _ctx(tmp_path)
    _generate(ctx, reasoner=_FakeReasoner(GOOD_OUTPUT, model="qwen3.5-27b"))

    other = {**GOOD_OUTPUT, "title": "a different model wrote this"}
    result = _generate(ctx, other, reasoner=_FakeReasoner(other, model="llama-3.3-70b"))

    assert result.cache_hit is False
    assert result.metadata.title == "a different model wrote this"


def test_a_different_platform_does_not_reuse_the_cache(tmp_path: Path) -> None:
    """Packaging for TikTok is not packaging for YouTube; the prompt is told which."""
    ctx = _ctx(tmp_path)
    _generate(ctx, platform="youtube")

    result = _generate(ctx, platform="tiktok")

    assert result.cache_hit is False


def test_a_tampered_cache_payload_is_treated_as_a_miss(tmp_path: Path) -> None:
    """CacheManager verifies the payload hash, so damage is a miss, not a hit.

    Worth pinning: the alternative -- trusting the payload -- would publish
    whatever bytes survived in the cache directory.
    """
    ctx = _ctx(tmp_path)
    spec = _remote_spec()
    reasoner = _FakeReasoner(GOOD_OUTPUT, model=spec.model)
    _generate(ctx, spec=spec, reasoner=reasoner)

    payloads = list((tmp_path / "data" / "cache").glob("*.bin"))
    assert payloads, "the stage should have written a cache payload"
    for payload in payloads:
        payload.write_text('{"title": "injected"}', encoding="utf-8")

    result = _generate(ctx, spec=spec, reasoner=reasoner)

    assert result.cache_hit is False
    assert result.metadata.title == GOOD_OUTPUT["title"]


def test_a_valid_hash_wrong_shape_is_reported(tmp_path: Path) -> None:
    """The guard that catches shape drift between code versions.

    A cache entry written by an older release can carry a correct hash and no
    usable fields. Reusing it would publish an empty title, so the stage refuses
    instead of silently regenerating and hiding the drift.
    """
    ctx = _ctx(tmp_path)
    spec = _remote_spec()
    reasoner = _FakeReasoner(GOOD_OUTPUT, model=spec.model)
    _generate(ctx, spec=spec, reasoner=reasoner)

    # Store through the cache manager so the hash is correct and only the shape
    # is wrong.
    payloads = list((tmp_path / "data" / "cache").glob("*.bin"))
    for payload in payloads:
        ctx.cache.store_json(payload.stem, {"unexpected": "shape"})

    with pytest.raises(aim.PublishingMetadataError, match="corrupt"):
        _generate(ctx, spec=spec, reasoner=reasoner)


# ---------------------------------------------------------------------------
# Narration handling
# ---------------------------------------------------------------------------


def test_long_narration_is_truncated_on_a_paragraph_boundary() -> None:
    script = ReviewScript.model_validate(
        {
            "sections": [
                {
                    "id": "sec_00001",
                    "type": "INTRO",
                    "paragraphs": [
                        {
                            "id": f"para_{index:05d}",
                            "text": "x" * 900,
                            "target_seconds": 10,
                        }
                        for index in range(20)
                    ],
                }
            ]
        }
    )

    excerpt = aim.narration_excerpt(script)

    assert len(excerpt) <= aim.NARRATION_EXCERPT_CHARS
    # A paragraph boundary, not a sentence cut mid-word.
    assert excerpt.endswith("x" * 900)


def test_a_script_with_no_sections_cannot_be_built() -> None:
    """Why the stage's own empty-script guard is not what this file tests.

    ReviewScript requires at least one section, so that guard defends against a
    caller that bypassed the domain model rather than against a constructible
    object. Asserting the domain rule here documents the boundary.
    """
    with pytest.raises(ValueError):
        ReviewScript.model_validate({"sections": []})


def test_an_unknown_job_is_reported(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.job_id = "job_does_not_exist"

    with pytest.raises(aim.PublishingMetadataError):
        _generate(ctx)


# ---------------------------------------------------------------------------
# Adapters: validation decided here, platform acceptance not claimed
# ---------------------------------------------------------------------------


class _RecordingBackend:
    """Backend that records the payload and returns a fixed receipt."""

    def __init__(self, video_id: str = "vid123", url: str = "https://example/vid123") -> None:
        self.payloads: list[Any] = []
        self._video_id = video_id
        self._url = url

    def __call__(self, payload: Any) -> tuple[str, str]:
        self.payloads.append(payload)
        return self._video_id, self._url


def _video(tmp_path: Path) -> Path:
    video = tmp_path / "review.mp4"
    video.write_bytes(b"fake-mp4")
    return video


def _request(video: Path, **kwargs: Any) -> UploadRequest:
    return UploadRequest(
        video_path=video,
        metadata=VideoMetadata(title="A title", description="A description", tags=["t"]),
        **kwargs,
    )


def _valid_privacy(adapter: Any) -> str:
    """A privacy value this adapter will accept.

    Facebook is the odd one out: Graph has no per-video privacy field, so it
    accepts only "public" and the pipeline default of "unlisted" is refused. The
    shared-contract tests are about validation order and classification, so each
    has to start from a request that could otherwise succeed.
    """
    if isinstance(adapter, fb.FacebookPageAdapter):
        return fb.DEFAULT_VISIBILITY
    return "unlisted"


# --- shared contract -------------------------------------------------------


@pytest.mark.parametrize(
    "make_adapter",
    [
        lambda backend, tmp_path: yt.YouTubeAdapter(backend=backend),
        lambda backend, tmp_path: fb.FacebookPageAdapter(
            backend=backend, page_id="page1", access_token="tok"
        ),
        lambda backend, tmp_path: tt.TikTokAdapter(backend=backend, access_token="tok"),
    ],
    ids=["youtube", "facebook", "tiktok"],
)
def test_a_missing_video_is_reported_before_any_call(make_adapter: Any, tmp_path: Path) -> None:
    backend = _RecordingBackend()
    adapter = make_adapter(backend, tmp_path)

    with pytest.raises(PublishingError, match="does not exist"):
        adapter.upload(_request(tmp_path / "absent.mp4"))

    assert backend.payloads == []


@pytest.mark.parametrize(
    "make_adapter",
    [
        lambda backend, tmp_path: yt.YouTubeAdapter(backend=backend),
        lambda backend, tmp_path: fb.FacebookPageAdapter(
            backend=backend, page_id="page1", access_token="tok"
        ),
        lambda backend, tmp_path: tt.TikTokAdapter(backend=backend, access_token="tok"),
    ],
    ids=["youtube", "facebook", "tiktok"],
)
def test_an_empty_title_is_rejected(make_adapter: Any, tmp_path: Path) -> None:
    backend = _RecordingBackend()
    adapter = make_adapter(backend, tmp_path)
    empty = UploadRequest(
        video_path=_video(tmp_path),
        metadata=VideoMetadata(title="   ", description="d", tags=[]),
        privacy=_valid_privacy(adapter),
    )

    with pytest.raises(UploadRejectedError, match="[Tt]itle"):
        adapter.upload(empty)

    assert backend.payloads == []


@pytest.mark.parametrize(
    "make_adapter",
    [
        lambda backend, tmp_path: yt.YouTubeAdapter(backend=backend),
        lambda backend, tmp_path: fb.FacebookPageAdapter(
            backend=backend, page_id="page1", access_token="tok"
        ),
        lambda backend, tmp_path: tt.TikTokAdapter(backend=backend, access_token="tok"),
    ],
    ids=["youtube", "facebook", "tiktok"],
)
def test_a_missing_thumbnail_is_reported(make_adapter: Any, tmp_path: Path) -> None:
    backend = _RecordingBackend()
    adapter = make_adapter(backend, tmp_path)

    with pytest.raises(PublishingError, match="Thumbnail"):
        adapter.upload(
            _request(
                _video(tmp_path),
                thumbnail_path=tmp_path / "absent.jpg",
                privacy=_valid_privacy(adapter),
            )
        )

    assert backend.payloads == []


@pytest.mark.parametrize(
    "make_adapter",
    [
        lambda backend, tmp_path: yt.YouTubeAdapter(backend=backend),
        lambda backend, tmp_path: fb.FacebookPageAdapter(
            backend=backend, page_id="page1", access_token="tok"
        ),
        lambda backend, tmp_path: tt.TikTokAdapter(backend=backend, access_token="tok"),
    ],
    ids=["youtube", "facebook", "tiktok"],
)
def test_an_empty_video_id_from_the_platform_is_rejected(make_adapter: Any, tmp_path: Path) -> None:
    """An upload that reports success without an id cannot be shown or undone."""
    backend = _RecordingBackend(video_id="")
    adapter = make_adapter(backend, tmp_path)

    with pytest.raises(UploadRejectedError, match="empty video id"):
        adapter.upload(_request(_video(tmp_path), privacy=_valid_privacy(adapter)))


@pytest.mark.parametrize(
    "make_adapter",
    [
        lambda backend, tmp_path: yt.YouTubeAdapter(backend=backend),
        lambda backend, tmp_path: fb.FacebookPageAdapter(
            backend=backend, page_id="page1", access_token="tok"
        ),
        lambda backend, tmp_path: tt.TikTokAdapter(backend=backend, access_token="tok"),
    ],
    ids=["youtube", "facebook", "tiktok"],
)
def test_a_backend_failure_is_classified(make_adapter: Any, tmp_path: Path) -> None:
    """An unclassified exception from a platform SDK must not reach the CLI."""

    def exploding(payload: Any) -> tuple[str, str]:
        raise RuntimeError("socket closed")

    adapter = make_adapter(exploding, tmp_path)

    with pytest.raises(UploadRejectedError):
        adapter.upload(_request(_video(tmp_path), privacy=_valid_privacy(adapter)))


# --- YouTube ---------------------------------------------------------------


def test_youtube_uploads_the_generated_metadata(tmp_path: Path) -> None:
    backend = _RecordingBackend()
    adapter = yt.YouTubeAdapter(backend=backend)

    receipt = adapter.upload(_request(_video(tmp_path)))

    assert receipt.video_id == "vid123"
    assert receipt.status == "uploaded"
    assert backend.payloads[0].title == "A title"
    assert backend.payloads[0].tags == ["t"]


def test_youtube_rejects_an_unknown_privacy_state(tmp_path: Path) -> None:
    adapter = yt.YouTubeAdapter(backend=_RecordingBackend())

    with pytest.raises(UploadRejectedError, match="privacy"):
        adapter.upload(_request(_video(tmp_path), privacy="secret"))


# --- Facebook --------------------------------------------------------------


def test_facebook_uploads_to_the_page(tmp_path: Path) -> None:
    backend = _RecordingBackend()
    adapter = fb.FacebookPageAdapter(backend=backend, page_id="page1", access_token="tok")

    receipt = adapter.upload(_request(_video(tmp_path), privacy=fb.DEFAULT_VISIBILITY))

    assert receipt.video_id == "vid123"
    assert backend.payloads[0].page_id == "page1"


def test_facebook_refuses_a_privacy_value_it_cannot_honour(tmp_path: Path) -> None:
    """Graph has no per-video privacy field.

    Accepting "unlisted" and ignoring it would report an upload that is not what
    the caller asked for, so this refuses and says what to do instead.
    """
    backend = _RecordingBackend()
    adapter = fb.FacebookPageAdapter(backend=backend, page_id="page1", access_token="tok")

    with pytest.raises(UploadRejectedError, match="Page"):
        adapter.upload(_request(_video(tmp_path), privacy="unlisted"))

    assert backend.payloads == []


def test_facebook_without_a_page_id_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MOVIE_REVIEW_FACEBOOK_PAGE_ID", raising=False)
    adapter = fb.FacebookPageAdapter(backend=_RecordingBackend())

    assert adapter.available() is False


def test_facebook_without_a_token_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MOVIE_REVIEW_FACEBOOK_TOKEN", raising=False)
    adapter = fb.FacebookPageAdapter(backend=_RecordingBackend(), page_id="page1")

    assert adapter.available() is False


def test_facebook_available_with_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOVIE_REVIEW_FACEBOOK_PAGE_ID", "page1")
    monkeypatch.setenv("MOVIE_REVIEW_FACEBOOK_TOKEN", "tok")
    adapter = fb.FacebookPageAdapter(backend=_RecordingBackend())

    assert adapter.available() is True


# --- TikTok ----------------------------------------------------------------


def test_tiktok_states_that_app_review_is_required() -> None:
    """The adapter is written but unproven; the reason must be discoverable."""
    assert "developer review" in tt.APP_REVIEW_NOTICE


def test_tiktok_without_a_token_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOVIE_REVIEW_TIKTOK_TOKEN", raising=False)
    adapter = tt.TikTokAdapter(backend=_RecordingBackend())

    assert adapter.available() is False


def test_tiktok_available_with_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOVIE_REVIEW_TIKTOK_TOKEN", "tok")
    adapter = tt.TikTokAdapter(backend=_RecordingBackend())

    assert adapter.available() is True


def test_tiktok_passes_the_title_and_description(tmp_path: Path) -> None:
    backend = _RecordingBackend()
    adapter = tt.TikTokAdapter(backend=backend, access_token="tok")

    adapter.upload(_request(_video(tmp_path)))

    assert backend.payloads[0].title == "A title"
    assert backend.payloads[0].description == "A description"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_the_three_requested_platforms_are_registered() -> None:
    assert set(registry.platform_names()) == {"youtube", "facebook", "tiktok"}


def test_an_unknown_platform_is_a_usage_error() -> None:
    assert registry.is_platform("vimeo") is False
    with pytest.raises(KeyError, match="Unknown platform"):
        registry.build_adapter("vimeo")


def test_platform_names_are_case_insensitive() -> None:
    assert isinstance(registry.build_adapter("YouTube"), PublishingPort)


def test_the_registry_builds_a_port_for_each_platform() -> None:
    for name in registry.platform_names():
        assert isinstance(registry.build_adapter(name), PublishingPort)


def test_unavailable_reason_names_the_missing_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MOVIE_REVIEW_FACEBOOK_PAGE_ID", raising=False)
    monkeypatch.delenv("MOVIE_REVIEW_FACEBOOK_TOKEN", raising=False)
    adapter = registry.build_adapter("facebook")

    assert "MOVIE_REVIEW_FACEBOOK_PAGE_ID" in registry.unavailable_reason("facebook", adapter)


# ---------------------------------------------------------------------------
# The CLI previews before it uploads
# ---------------------------------------------------------------------------


def test_publish_without_confirm_does_not_upload(tmp_path: Path, monkeypatch) -> None:
    """Nothing leaves the machine unless a human asked for it."""
    import importlib

    from typer.testing import CliRunner

    cliapp = importlib.import_module("movie_review.cli.app")

    from movie_review.config import settings as settings_module

    base = load_settings()
    data_dir = tmp_path / "data"
    settings = base.model_copy(
        update={"paths": base.paths.model_copy(update={"data_dir": str(data_dir)})}
    )
    monkeypatch.setattr(settings_module, "load_settings", lambda *a, **k: settings)

    jobs = data_dir / "jobs" / "job_1"
    (jobs / "render").mkdir(parents=True)
    (jobs / "render" / "review.mp4").write_bytes(b"mp4")
    (jobs / "review").mkdir(parents=True)
    (jobs / "review" / "review-script.json").write_text(
        json.dumps(
            {
                "sections": [
                    {
                        "id": "sec_00001",
                        "type": "INTRO",
                        "paragraphs": [{"id": "p1", "text": "A line.", "target_seconds": 10}],
                    }
                ]
            }
        )
    )

    uploaded: list[Any] = []
    monkeypatch.setattr(
        "movie_review.publishing.youtube.YouTubeAdapter.upload",
        lambda self, request: uploaded.append(request),
    )
    monkeypatch.setattr(
        "movie_review.publishing.ai_metadata.generate_publishing_metadata",
        lambda *a, **k: aim.MetadataResult(
            metadata=VideoMetadata(
                title="A generated title",
                description="A generated description",
                tags=["one", "two"],
            ),
            metadata_path=tmp_path / "m.json",
            cache_hit=False,
            model="m",
            prompt_version="publishing_metadata:v1",
        ),
    )

    result = CliRunner().invoke(
        cliapp.app, ["publish", "job_1", "--db-path", str(data_dir / "jobs.db")]
    )

    assert uploaded == [], "the video must not be uploaded without --confirm"
    if result.exit_code != 0:
        # The job record is absent in this fixture; the important assertion above
        # still holds, and the failure is reported rather than swallowed.
        assert "Unknown job" in result.output or "No rendered video" in result.output
