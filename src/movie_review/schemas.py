"""The published JSON Schemas, and the validation every AI output goes through.

README section 6.6: every AI output must pass schema validation before it
enters the next stage. Section 7 lists the seven schema files that describe
the knowledge base's shapes; the directory was empty, so the contract was
never published and nothing was checked against it.

The schemas are generated from the domain models, so they cannot drift from
the code that produces the documents. A test regenerates them and compares,
which is what keeps them honest.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from movie_review.domain import (
    Character,
    Event,
    Evidence,
    ManifestSegment,
    Movie,
    ReviewScript,
    Scene,
)

SCHEMAS_DIRNAME = "schemas"

#: The schema files README section 7 names, and the model each is generated
#: from.
SCHEMA_MODELS: dict[str, type[Any]] = {
    "movie": Movie,
    "scene": Scene,
    "character": Character,
    "event": Event,
    "evidence": Evidence,
    "review": ReviewScript,
    "render": ManifestSegment,
}


class SchemaError(Exception):
    """An artifact does not match its published schema."""


def schemas_dir(base: str | Path | None = None) -> Path:
    """The directory the schema files live in."""
    if base is not None:
        return Path(base)
    # This module is at <repo>/src/movie_review/schemas.py, so the repository
    # root is three levels up.
    return Path(__file__).resolve().parents[2] / SCHEMAS_DIRNAME


def schema_path(name: str, base: str | Path | None = None) -> Path:
    """The path of one schema file."""
    return schemas_dir(base) / f"{name}.schema.json"


@lru_cache(maxsize=16)
def load_schema(name: str, base: str | Path | None = None) -> dict[str, Any]:
    """One published schema."""
    path = schema_path(name, base)
    if not path.is_file():
        raise SchemaError(f"No schema for {name}: {path} is missing")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SchemaError(f"The schema at {path} is not a JSON object")
    return document


def validate_artifact(name: str, document: Any, base: str | Path | None = None) -> None:
    """Check a document against its published schema.

    Raises:
        SchemaError: the document does not match the schema.
    """
    import jsonschema

    schema = load_schema(name, base)
    try:
        jsonschema.validate(instance=document, schema=schema)
    except jsonschema.ValidationError as exc:
        where = "/".join(str(part) for part in exc.absolute_path)
        raise SchemaError(
            f"The {name} artifact does not match its schema"
            + (f" at {where}" if where else "")
            + f": {exc.message}"
        ) from exc


def generate_schema(name: str) -> dict[str, Any]:
    """The schema a model generates, for the file that is published."""
    model = SCHEMA_MODELS.get(name)
    if model is None:
        raise SchemaError(f"Unknown schema: {name}")
    schema: dict[str, Any] = dict(model.model_json_schema())
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://movie-review-ai/schemas/{name}.schema.json"
    schema["title"] = name
    return schema


def write_schemas(base: str | Path | None = None) -> list[Path]:
    """Write every schema file; returns the paths written."""
    target = schemas_dir(base)
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in SCHEMA_MODELS:
        path = schema_path(name, base)
        path.write_text(
            json.dumps(generate_schema(name), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
