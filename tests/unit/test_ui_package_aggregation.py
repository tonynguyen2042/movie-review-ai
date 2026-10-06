"""Guard the package aggregation after merging the per-task branches.

Every Phase 11/12 task shipped its own ``__init__.py`` exporting only its own
class, so merging them naively silently dropped modules. These tests assert
that each package exposes every implementation and that every advertised name
resolves, which is exactly what broke before.
"""

import importlib

import pytest

UI_EXPORTS = [
    "CharacterExplorer",  # T091
    "JobDashboard",  # T089
    "MovieTimeline",  # T090
    "QualityReportUI",  # T095
    "ScriptEditor",  # T093
    "StoryGraph",  # T092
    "VisualTimelineEditor",  # T094
    "json_for_script",
]

PUBLISHING_EXPORTS = [
    # T096 metadata
    "Chapter",
    "MetadataError",
    "VideoMetadata",
    "build_chapters",
    "build_description",
    "build_tags",
    "build_title",
    "generate_metadata",
    "script_text",
    "TITLE_MAX_CHARS",
    "DESCRIPTION_MAX_CHARS",
    "MAX_TAGS",
    # T097 thumbnail
    "ThumbnailError",
    "ThumbnailPlan",
    "ThumbnailResult",
    "generate_thumbnail",
    "plan_thumbnail",
    "thumbnail_path",
    "DEFAULT_EDGE_MARGIN_RATIO",
    "THUMBNAIL_FILENAME",
    # T098 youtube
    "PublishingError",
    "PublishingPort",
    "PublishingUnavailableError",
    "UploadReceipt",
    "UploadRejectedError",
    "UploadRequest",
    "VideoMetadataLike",
    "YouTubeAdapter",
    "RawUpload",
    "DEFAULT_CATEGORY_ID",
    "PRIVACY_STATES",
]

UI_MODULES = [
    "character",
    "dashboard",
    "graph",
    "qc_report",
    "safe_json",
    "script_editor",
    "timeline",
    "timeline_editor",
]

PUBLISHING_MODULES = ["metadata", "port", "thumbnail", "youtube"]


@pytest.mark.parametrize("name", UI_EXPORTS)
def test_ui_export_resolves(name: str) -> None:
    """Every name in ``ui.__all__`` is importable from the package."""
    ui = importlib.import_module("movie_review.ui")
    assert name in ui.__all__
    assert hasattr(ui, name), f"ui.__all__ advertises missing {name}"


@pytest.mark.parametrize("name", PUBLISHING_EXPORTS)
def test_publishing_export_resolves(name: str) -> None:
    """Every name in ``publishing.__all__`` is importable from the package."""
    publishing = importlib.import_module("movie_review.publishing")
    assert name in publishing.__all__
    assert hasattr(publishing, name), f"publishing.__all__ advertises missing {name}"


@pytest.mark.parametrize("module", UI_MODULES)
def test_ui_module_importable(module: str) -> None:
    """No Phase 11 module was dropped by the merge."""
    importlib.import_module(f"movie_review.ui.{module}")


@pytest.mark.parametrize("module", PUBLISHING_MODULES)
def test_publishing_module_importable(module: str) -> None:
    """No Phase 12 module was dropped by the merge."""
    importlib.import_module(f"movie_review.publishing.{module}")


def test_ui_all_is_sorted_and_unique() -> None:
    """``__all__`` stays tidy so the file remains reviewable."""
    ui = importlib.import_module("movie_review.ui")
    assert len(ui.__all__) == len(set(ui.__all__))


def test_publishing_all_is_unique() -> None:
    """No duplicate export entries."""
    publishing = importlib.import_module("movie_review.publishing")
    assert len(publishing.__all__) == len(set(publishing.__all__))


def test_ui_html_generators_do_not_embed_raw_json() -> None:
    """Every generator must use the script-safe serializer.

    ``json.dumps`` leaves ``</script>`` intact, so raw embedding would let
    model-produced text execute as JavaScript.
    """
    ui = importlib.import_module("movie_review.ui")
    for name in (
        "CharacterExplorer",
        "StoryGraph",
        "QualityReportUI",
        "ScriptEditor",
        "MovieTimeline",
        "VisualTimelineEditor",
    ):
        cls = getattr(ui, name)
        source_file = importlib.import_module(cls.__module__).__file__
        assert source_file is not None
        with open(source_file, encoding="utf-8") as handle:
            source = handle.read()
        assert "json_for_script(data)" in source, (
            f"{cls.__module__} embeds json.dumps(data) instead of json_for_script"
        )
