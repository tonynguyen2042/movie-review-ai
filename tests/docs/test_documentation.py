"""The documents README section 7 promises have to exist and be right.

T169. The `docs/` directory held the user guide and the desktop-app guide,
and nothing else. README §7 lists five more:

- `docs/architecture.md`
- `docs/pipeline.md`
- `docs/schemas.md`
- `docs/model-selection.md`
- `docs/troubleshooting.md`

The user guide also still named four configuration keys that had been
removed — `runtime.backend`, `memory.reserve_mb`, `privacy.telemetry` and
`logging.json_output` — so it told a reader to set switches that no
longer exist.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

#: The five documents README section 7 lists.
SECTION_7_DOCS = (
    "architecture.md",
    "pipeline.md",
    "schemas.md",
    "model-selection.md",
    "troubleshooting.md",
)

#: The configuration keys that were removed, and so must not be documented.
REMOVED_KEYS = (
    "runtime.backend",
    "runtime.device",
    "memory.reserve_mb",
    "privacy.telemetry",
    "logging.json_output",
    "pipeline.evidence_required",
)


def _read(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def test_every_named_document_exists() -> None:
    """The directory held two guides and none of the five."""
    for name in SECTION_7_DOCS:
        path = DOCS / name
        assert path.is_file(), f"{name} is missing"
        assert path.stat().st_size > 2000, f"{name} is a stub"


def test_every_document_is_linked_from_the_guide() -> None:
    """A document nobody can find is a document nobody reads."""
    guide = _read("GETTING-STARTED.md")
    for name in SECTION_7_DOCS:
        assert name in guide, f"the guide never links {name}"


def test_the_guide_names_no_removed_setting() -> None:
    """It told a reader to set switches that no longer exist."""
    guide = _read("GETTING-STARTED.md")
    for key in REMOVED_KEYS:
        assert key not in guide, f"the guide still names {key}"


def test_the_architecture_document_describes_the_layers() -> None:
    """It has to be about the code, not about the idea of the code."""
    document = _read("architecture.md")
    for term in ("domain", "port", "adapter", "pipeline", "storage", "cache"):
        assert term in document, f"the architecture document does not mention {term}"


def test_the_pipeline_document_names_every_stage() -> None:
    """A stage that is not documented is a stage nobody knows about."""
    from movie_review.pipeline.orchestrator import STAGE_SEQUENCE

    document = _read("pipeline.md")
    for name, _ in STAGE_SEQUENCE:
        assert name in document, f"the pipeline document does not mention {name}"


def test_the_schemas_document_names_every_schema() -> None:
    from movie_review.schemas import SCHEMA_MODELS

    document = _read("schemas.md")
    for name in SCHEMA_MODELS:
        assert f"{name}.schema.json" in document, f"{name} is not documented"


def test_the_model_document_names_every_profile() -> None:
    from movie_review.config.settings import available_profiles

    document = _read("model-selection.md")
    for name in available_profiles():
        assert f"`{name}`" in document, f"the {name} profile is not documented"


def test_the_troubleshooting_document_names_the_real_errors() -> None:
    """It has to help with the failures that actually happen."""
    document = _read("troubleshooting.md")
    for phrase in (
        "is not installed",
        "exceeds limit",
        "NEEDS_REVIEW",
        "ffprobe",
        "cloud_ai",
    ):
        assert phrase in document, f"the troubleshooting document does not cover {phrase}"


def test_the_documents_do_not_promise_anything_false() -> None:
    """The source-footage controls are not a legal guarantee."""
    document = _read("pipeline.md") + _read("troubleshooting.md")
    assert "not a legal guarantee" in document or "not legal advice" in document
    assert re.search(r"not\s+a\s+legal\s+guarantee", document)


def test_every_document_has_a_title() -> None:
    for name in SECTION_7_DOCS:
        document = _read(name)
        assert document.startswith("# "), f"{name} has no title"
