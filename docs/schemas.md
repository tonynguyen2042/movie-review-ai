# The schemas

Seven JSON Schema files, published under [`schemas/`](../schemas/), and the
validation every AI output goes through before it enters the next stage.

---

## The files

| File | Describes | Generated from |
|---|---|---|
| `movie.schema.json` | the ingested media metadata | `domain/movie.py` |
| `scene.schema.json` | one scene of the timeline | `domain/scene.py` |
| `character.schema.json` | one character | `domain/character.py` |
| `event.schema.json` | one story event | `domain/event.py` |
| `evidence.schema.json` | one piece of evidence | `domain/evidence.py` |
| `review.schema.json` | the review script | `domain/review.py` |
| `render.schema.json` | one segment of the render manifest | `domain/render.py` |

Each file is a JSON Schema draft 2020-12 document:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://movie-review-ai/schemas/event.schema.json",
  "title": "event",
  "properties": { "...": "..." },
  "required": ["id", "type", "timestamp", "description"]
}
```

---

## They are generated, not hand-written

The schemas are produced from the Pydantic domain models:

```python
schema = model.model_json_schema()
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
schema["$id"] = f"https://movie-review-ai/schemas/{name}.schema.json"
```

That is deliberate. A hand-written schema drifts from the model that
produces the document, and a drifted schema rejects valid output — which
is worse than having no schema, because the failure looks like the model's
fault.

The generator is the source of truth. The file is the published copy.

To regenerate them:

```bash
uv run python -c "from movie_review.schemas import write_schemas; write_schemas()"
```

A test regenerates every schema and compares it against the published file,
so a change to a model that is not followed by a regeneration **fails the
suite**. That is what keeps them honest.

---

## The validation

Every AI output is checked against its schema before it is persisted.

| Stage | Validated against |
|---|---|
| `characters` | `character.schema.json` |
| `events` | `event.schema.json` |
| `review` | `review.schema.json` |

```python
from movie_review.schemas import SchemaError, validate_artifact

try:
    validate_artifact("event", event.model_dump(mode="json"))
except SchemaError as exc:
    raise EventExtractionError(str(exc)) from exc
```

A document that does not match its schema **fails the stage**. The stage
does not persist a half-valid result and does not let the next stage
inherit it.

The error names the place it went wrong:

```text
The event artifact does not match its schema at properties/type: 'NOT_A_TYPE' is not one of [...]
```

### Why the validator is a dependency

The project uses `jsonschema`, the standard validator. It is a real
addition to the dependency set, and it is there because the spec asks for
schema validation by name and because a half-implemented validator is a
validator that misses things.

---

## Using the schemas yourself

The files are a contract. Anything that reads a movie's output can check it
against them without knowing anything about this project.

```bash
# with ajv
ajv validate -s schemas/event.schema.json -d events.json

# with python
python -c "
import json, jsonschema
schema = json.load(open('schemas/event.schema.json'))
document = json.load(open('events.json'))
jsonschema.validate(document, schema)
"
```

The schemas are published under a stable `$id`, so they can be referenced
from other projects.

---

## What is not in a schema

The schemas describe **shapes**, not meanings. An event that matches
`event.schema.json` is well-formed; it is not necessarily true. That is
what the verification stage is for: it checks the script's claims against
the evidence, and a claim the evidence does not support is removed or
marked `INSUFFICIENT_EVIDENCE`.

A shape that passes is the floor, not the ceiling.
