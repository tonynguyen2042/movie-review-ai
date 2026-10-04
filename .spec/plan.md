# Implementation Plan — movie-review-ai

**Version:** 1.1

## 1. Architecture

```text
CLI
 │
 ▼
Application Services
 ├── Job Manager
 ├── Pipeline Orchestrator
 ├── Artifact Manager
 ├── Cache Manager
 └── Resource Manager
 │
 ▼
Domain
 ├── Movie
 ├── Scene
 ├── Character
 ├── Event
 ├── Evidence
 ├── Story
 ├── Review
 └── Render
 │
 ▼
Ports
 ├── Media
 ├── ASR
 ├── Diarization
 ├── VLM
 ├── Reasoning
 └── TTS
 │
 ▼
Adapters / Infrastructure
 ├── FFmpeg
 ├── PySceneDetect
 ├── Whisper
 ├── Qwen3-VL
 ├── Qwen3.5
 ├── Qwen3-TTS
 ├── SQLite
 └── Filesystem
```

Dependency direction:

```text
CLI → Application → Domain
Application → Ports
Infrastructure → Ports
Adapters → Ports
```

Domain must not import:

- MLX
- FFmpeg
- SQLite
- Typer
- model-specific SDKs

## 2. Technology

Initial target:

- Python 3.12+
- Pydantic 2
- Typer
- SQLite
- filesystem artifacts
- FFmpeg
- PySceneDetect
- MLX-compatible model adapters where supported

## 3. Pipeline Stage Contract

Every stage follows:

```text
validate input
→ check cache
→ execute
→ validate output
→ persist artifact
→ record metrics
→ mark complete
```

Every stage must be idempotent.

## 4. Artifact Layout

```text
data/
└── jobs/
    └── <job_id>/
        ├── manifest.json
        ├── media/
        ├── scenes/
        ├── frames/
        ├── transcript/
        ├── diarization/
        ├── vision/
        ├── characters/
        ├── story/
        ├── review/
        ├── tts/
        ├── render/
        ├── qc/
        └── logs/
```

## 5. Model Profile

Balanced default:

```text
ASR       Whisper large-v3-turbo
Vision    Qwen3-VL
Reasoning Qwen3.5-27B
Critic    disabled
TTS       Qwen3-TTS 1.7B
```

Quality mode may add a larger critic model.

Model choice must ultimately be benchmark-driven.

## 6. Memory Strategy

Prefer:

```text
ASR
 ↓ unload
VLM
 ↓ unload
Reasoning
 ↓ unload
TTS
```

unless measurement demonstrates safe simultaneous residency.

OOM recovery:

```text
detect
→ stop stage
→ release model
→ clear recoverable caches
→ reduce workload
→ retry
```

## 7. Prompt Strategy

Prompts live under:

```text
config/prompts/
```

Every prompt has a version.

Prompt changes invalidate dependent AI artifacts.

## 8. Testing Strategy

### Unit

Domain, schemas, state transitions, cache keys, artifact integrity.

### Integration

SQLite, artifact manager, CLI, pipeline orchestration.

### Golden AI Evaluation

Measure:

- plot accuracy
- character accuracy
- evidence coverage
- hallucination
- timeline consistency
- script quality

Large models are not required for normal CI.

## 9. Observability

Use structured JSON logs.

Minimum context:

```text
job_id
stage
event
status
duration_ms
error
```

Model metrics should include:

```text
model
input_tokens
output_tokens
latency
tokens_per_second
memory
```

## 10. Failure Recovery

Failures must be classified.

Examples:

```text
media-invalid
schema-invalid
model-load-failed
model-oom
artifact-corrupt
dependency-failed
```

Recoverable failures may retry.

Repeated failure must stop rather than loop indefinitely.

## 11. Git / Task Lifecycle

Git is part of implementation, not a post-processing step.

### Task lifecycle

```text
master
  ↓
create task branch
  ↓
milestone 1 → test → commit
  ↓
milestone 2 → test → commit
  ↓
...
  ↓
full test suite
  ↓
acceptance validation
  ↓
task state [x]
  ↓
push branch
  ↓
create PR → master
  ↓
await review
```

### Branch

```text
task/<task-id>-<short-description>
```

Example:

```text
task/T023-qwen3-vl-adapter
```

### Commit

Every meaningful milestone must be committed:

```text
feat(T023): add VLM port
feat(T023): implement Qwen3-VL adapter
test(T023): add VLM contract tests
```

### PR

A completed task automatically creates a PR to `master`.

PR creation requires:

```bash
pytest -q
```

to pass.

Configured lint/type checks must also pass.

PR merge remains manual by default.

## 12. Implementation Loop

For every task:

```text
identify task
→ create branch
→ inspect repository
→ inspect dependencies
→ search existing implementation
→ identify contracts
→ define milestones
→ implement milestone
→ targeted test
→ commit milestone
→ repeat
→ full tests
→ acceptance validation
→ update task state
→ final commit
→ push
→ create PR
```

## 13. Phase Plan

### Phase 0 — Foundation

T001–T009

### Phase 1 — Media Intelligence

T010–T015

### Phase 2 — Audio Intelligence

T016–T021

### Phase 3 — Visual Intelligence

T022–T026

### Phase 4 — Movie Knowledge Base

T027–T039

### Phase 5 — Review Intelligence

T040–T050

### Phase 6 — Narration

T051–T055

### Phase 7 — Visual Editing

T056–T062

### Phase 8 — Quality & Benchmark

T063–T077

### Phase 9 — Golden Tests

T078–T083

### Phase 10 — CLI Completion

T084–T088

### Phase 11 — Optional UI

T089–T095

### Phase 12 — Optional Publishing

T096–T098

## 14. Phase Completion Gate

A phase is complete only when:

- all tasks are `[x]`
- all tests pass
- contracts are stable
- failure paths are implemented
- artifacts are reproducible
- documentation is current
- task branches have PRs
- no blocking TODO remains
