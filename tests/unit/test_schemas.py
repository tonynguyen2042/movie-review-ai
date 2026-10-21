"""The published schemas must exist, and the AI outputs must match them.

T158. README section 6.6 says every AI output must pass schema validation
before it enters the next stage, and section 7 lists seven schema files that
describe the knowledge base's shapes. The `schemas/` directory was empty, so
the contract was never published and nothing was checked against it.

The schemas are generated from the domain models, so they cannot drift from
the code that produces the documents.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from movie_review.domain import Event, EventType, ReviewScript
from movie_review.schemas import (
    SCHEMA_MODELS,
    SchemaError,
    generate_schema,
    load_schema,
    schema_path,
    validate_artifact,
    write_schemas,
)

#: The schema files README section 7 names.
SECTION_7_SCHEMAS = [
    "movie",
    "scene",
    "character",
    "event",
    "evidence",
    "review",
    "render",
]


def test_every_named_schema_file_exists() -> None:
    """The directory was empty."""
    for name in SECTION_7_SCHEMAS:
        path = schema_path(name)
        assert path.is_file(), f"{path} is missing"
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["$schema"].startswith("https://json-schema.org/")
        assert document["title"] == name


def test_the_schemas_are_the_ones_the_readme_names() -> None:
    assert set(SCHEMA_MODELS) == set(SECTION_7_SCHEMAS)


def test_the_published_schemas_match_the_models() -> None:
    """A schema that has drifted from its model is worse than none."""
    for name in SCHEMA_MODELS:
        published = load_schema(name)
        generated = generate_schema(name)
        assert published == generated, f"the {name} schema has drifted"


def test_writing_the_schemas_is_idempotent(tmp_path: Path) -> None:
    written = write_schemas(tmp_path)
    assert len(written) == len(SCHEMA_MODELS)
    for path in written:
        assert path.is_file()


def test_a_valid_document_passes() -> None:
    event = Event(
        id="event_00001",
        type=EventType.DISCOVERY,
        timestamp=10.0,
        description="Someone finds something.",
    )
    validate_artifact("event", event.model_dump(mode="json"))


def test_an_invalid_document_is_rejected() -> None:
    """The validation has to actually reject something."""
    with pytest.raises(SchemaError) as excinfo:
        validate_artifact("event", {"id": "event_00001", "type": "NOT_A_TYPE"})
    assert "does not match its schema" in str(excinfo.value)


def test_a_missing_field_is_rejected() -> None:
    with pytest.raises(SchemaError):
        validate_artifact("event", {"id": "event_00001"})


def test_an_unknown_schema_is_reported(tmp_path: Path) -> None:
    with pytest.raises(SchemaError, match="No schema"):
        load_schema("nope", tmp_path)


def test_the_review_script_validates() -> None:
    script = ReviewScript.model_validate(
        {
            "sections": [
                {
                    "id": "sec_001",
                    "type": "hook",
                    "paragraphs": [
                        {
                            "id": "p1",
                            "text": "The hero walks in.",
                            "target_seconds": 10,
                            "claims": [],
                            "visual_intent": "s",
                        }
                    ],
                }
            ]
        }
    )
    validate_artifact("review", script.model_dump(mode="json"))
