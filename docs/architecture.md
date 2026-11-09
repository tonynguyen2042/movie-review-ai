# Architecture

How the code is arranged, and why it is arranged that way.

The rule that shapes everything here: **the domain knows nothing about the
outside world.** The domain models — a job, a scene, an event, a claim — do
not import SQLite, MLX, FFmpeg, Typer or any model SDK. They are plain
Pydantic models with no behaviour beyond validation.

That rule is what makes the rest possible. It is worth knowing where the
line is drawn before reading any of the other documents.

---

## The layers

```text
                     ┌──────────────────────────────────────────┐
   cli/  ui/         │ the CLI, the dashboard, the desktop app   │
                     └───────────────────┬──────────────────────┘
                                         │
                     ┌───────────────────▼──────────────────────┐
   pipeline/         │ the stages, in order, and the orchestrator │
                     └───────────────────┬──────────────────────┘
                                         │
        ┌────────────────┬───────────────┼───────────────┬────────────────┐
        │                │               │               │                │
  ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
  │ asr/      │   │ vision/   │   │ reasoning/│   │ tts/      │   │ media/    │
  │ diarizat. │   │           │   │           │   │           │   │ rendering/│
  └─────┬─────┘   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
        │                │               │               │                │
        └────────────────┴───────┬───────┴───────────────┴────────────────┘
                                  │
                        ┌─────────▼─────────┐
                        │ the ports         │  one per model kind
                        │ (port.py in each) │
                        └─────────┬─────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
  ┌─────▼──────┐          ┌───────▼──────┐          ┌───────▼──────┐
  │ mlx        │          │ openai-      │          │ the stubs    │
  │ (local)    │          │ compatible   │          │ (tests)      │
  └────────────┘          └──────────────┘          └──────────────┘
```

### The domain — `domain/`

Plain models. `Job`, `Scene`, `SceneAnalysis`, `Event`, `Evidence`,
`Character`, `Claim`, `ReviewScript`, `RenderManifest`, `ModelRun`.

They validate and they carry identity. They do not do anything.

### The ports — `asr/port.py`, `vision/port.py`, `reasoning/port.py`, `tts/port.py`, `diarization/port.py`

One abstract class per kind of model. Each declares the calls the pipeline
needs and nothing else:

```python
class ReasoningPort(ABC):
    @abstractmethod
    def complete(self, prompt: str, *, temperature: float = 0.4) -> str: ...

    def runtime(self) -> str:
        """The runtime serving this model."""
        return type(self).__name__

    def last_usage(self) -> ModelUsage | None:
        """The tokens the last call cost, when the runtime reports them."""
        return None
```

The pipeline never imports a model SDK. It asks for a port, and the factory
decides which adapter satisfies it.

### The adapters — `qwen.py`, `openai_compat.py`, `whisper_mlx.py`

Each adapter implements one port for one runtime. The factory reads the
model spec and picks:

```python
def build_reasoning_adapter(spec: ModelSpec) -> ReasoningPort:
    if spec.base_url:
        return OpenAICompatAdapter(spec.model, spec.base_url, ...)
    return QwenReasoningAdapter(spec.model, ...)
```

The privacy policy travels **on the spec**, not as a separate argument, so
an adapter cannot be built that ignores it.

### The pipeline — `pipeline/`

`orchestrator.py` holds the stage registry and the twenty-three stage
closures. Every stage follows the same shape:

```text
validate input → cache lookup → execute → validate output → persist → metrics → complete
```

and every stage is idempotent: running it twice produces the same result
and the same artifacts. The cache is content-addressed, so a cache hit is
the same answer, not a stale one.

### The storage — `storage/`

`schema.py` holds the DDL and the migrations. `database.py` opens the
connection and applies them. `repositories.py` is the only module that
writes SQL.

The database is the **queryable copy**; the artifact files are the **record
of record**. A stage writes both. The stages that need to query read the
database, which is why the analyses survive a moved or pruned artifact
tree.

### The artifacts — `artifacts/`

Every file a job produces is written through `artifacts/manager.py`, which
records the hash and validates that no path escapes the job's directory.
`artifacts/integrity.py` checks a job's files against their recorded
hashes.

### The cache — `cache/`

`keys.py` builds the cache key from the input hash, the model, the prompt
version, the stage version and the generation config. `manager.py` stores
the payload and a sidecar recording its hash, and removes any entry whose
hash does not match on lookup.

---

## Where the state lives

A job has two homes, on purpose:

| | What it is | Who reads it |
|---|---|---|
| the artifact tree | `<data_dir>/jobs/<job_id>/…` | the operators, the renderer, the validator |
| the database | `<data_dir>/jobs.db` | the pipeline, the dashboard, the CLI |

The tree holds the artifacts: `media/media.json`, `scenes/scenes.json`,
`transcript/transcript.json`, `vision/vision.json`, `story/story-arcs.json`,
`review/review-script.json`, `tts/narration.wav`, `render/render.mp4`,
`qc/quality-report.json`, and the rest.

The database holds the queryable rows: the job record, the scenes, the
transcript segments, the events, the claims, the artifacts, and the record
of every model invocation.

---

## The configuration

`config/config.yaml` holds the product controls and the model catalogue:
the `profiles` section is the catalog, and `models.profile` (or `--profile`)
selects from it. `config/prompts/` holds the prompt templates, one file per
version.

Settings are read in this order, highest first:

1. explicit CLI options
2. `MOVIE_REVIEW_*` environment variables
3. `config/config.yaml` (or the file `--config` / `MOVIE_REVIEW_CONFIG`
   points at)
4. the built-in defaults

Nothing about a model name, a path, a duration, a threshold or a prompt
version is hard-coded in the code. If a value is in the source, it is a
default the configuration can override.

---

## What is deliberately absent

- **No HTTP client dependency.** The remote adapters use `urllib` from the
  standard library, through `remote/http.py`.
- **No vector database.** The knowledge base is JSON and SQLite. Retrieval
  is a keyword search over the evidence, and it works.
- **No framework.** The CLI is Typer; the dashboard is `http.server`. There
  is no web framework and no ORM.
- **No telemetry.** The project sends nothing anywhere. `privacy.cloud_ai`
  is the only switch, and it is off by default.

---

## Where to look next

- [pipeline.md](pipeline.md) — the stages, what each one does, what each
  one writes.
- [schemas.md](schemas.md) — the published JSON Schemas and what validates
  against them.
- [model-selection.md](model-selection.md) — the profiles, the slots, and
  how to measure a model before choosing it.
- [troubleshooting.md](troubleshooting.md) — what to do when something
  fails.
- [GETTING-STARTED.md](GETTING-STARTED.md) — how to run the thing.
