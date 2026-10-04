# Constitution — movie-review-ai

**Version:** 1.1  
**Status:** Active

## 1. Mission

`movie-review-ai` converts a full-length movie into an approximately 20-minute, YouTube-style movie review using a local-first AI pipeline.

The system must prioritize factual accuracy, evidence traceability, restartability, reproducibility, and safe automation.

## 2. Authority

Project rules are interpreted in this order:

1. `constitution.md`
2. `spec.md`
3. `plan.md`
4. `tasks.md`
5. `AGENTS.md`

A lower-level document must not silently override a higher-level rule.

## 3. Core Principles

### P1 — Evidence First

Every factual plot claim must be traceable to the Movie Knowledge Base.

Prefer `INSUFFICIENT_EVIDENCE` over guessing.

### P2 — Deterministic Before Generative

Use deterministic tooling for:

- FFmpeg
- PySceneDetect
- timestamps
- hashing
- duration calculations
- filesystem operations
- schema validation
- SQLite persistence

Use AI for:

- interpretation
- visual understanding
- reasoning
- classification
- story analysis
- review writing

### P3 — Structured Data Is the Contract

Pipeline stages communicate through validated structured data.

AI output must be schema-constrained, parsed, validated, normalized, and persisted.

Markdown is presentation, not a canonical data contract.

### P4 — Pipeline Must Be Restartable

Every stage must be independently resumable.

Artifacts must record relevant:

- job ID
- stage
- stage version
- input hash
- output hash
- model/runtime
- prompt version
- generation configuration

### P5 — No Silent Hallucination

Claim statuses:

- `SUPPORTED`
- `PARTIALLY_SUPPORTED`
- `CONTRADICTED`
- `INSUFFICIENT_EVIDENCE`

Major contradicted claims must be repaired or removed.

### P6 — Model Agnostic Architecture

ASR, VLM, reasoning LLM, diarization, and TTS must be accessed through ports/adapters.

Changing a model must not require changing domain logic.

### P7 — Local First

Movie content remains local by default.

Cloud AI, external metadata, telemetry, and publishing are opt-in.

### P8 — Resource Awareness

Apple Silicon unified memory is shared by CPU and GPU.

The system must:

- estimate memory requirements
- avoid unnecessary simultaneous model residency
- unload models between major stages where appropriate
- recover from memory pressure/OOM
- expose resource metrics

### P9 — Hierarchical Understanding

Movie understanding is hierarchical:

```text
movie
 → sequence
 → scene
 → event
 → evidence
```

Never depend on putting an entire movie into one context window.

### P10 — Review Is Not a Transcript

The final review must provide:

- narrative structure
- commentary
- interpretation
- pacing
- context
- selective plot explanation

It must not merely repeat the transcript.

### P11 — Facts and Interpretation Are Separate

Represent separately:

- plot fact
- character fact
- timeline fact
- dialogue reference
- interpretation
- theme
- opinion

### P12 — Downstream Invalidation

Changing a review paragraph invalidates only dependent TTS/render artifacts.

It must not unnecessarily invalidate movie analysis.

### P13 — Quality Gates

Validate:

- media integrity
- evidence coverage
- timeline
- character consistency
- claim correctness
- TTS completeness
- visual alignment
- final render integrity

### P14 — No Fake Legal Guarantees

A fixed clip duration or percentage is not automatically legally safe.

Copyright controls are product configuration, not legal advice.

### P15 — Explicit Scope

V1 scope:

```text
movie
 → media intelligence
 → movie knowledge base
 → evidence-backed review
 → narration
 → edited review video
 → quality control
```

Out of scope:

- copyright disputes
- monetization
- autonomous publishing by default
- movie generation/remakes
- mandatory cloud AI
- distributed multi-machine inference
- UI before CLI stability
- mandatory vector database

### P16 — Test Before Optimization

Correctness and reproducibility come before throughput optimization.

### P17 — No Unrequested Architecture Drift

Do not introduce:

- vector DB
- web UI
- distributed services
- alternative storage
- alternative model runtime

unless explicitly approved or required by the specification.

### P18 — Definition of Done

A task is not complete until:

- implementation exists
- contracts are valid
- tests pass
- acceptance criteria pass
- documentation is updated where required
- task state is `[x]`
- every meaningful milestone is committed
- task branch is pushed
- a PR into `master` is created

## 4. Mandatory Git Task Isolation

Every implementation task is an independently reviewable Git unit.

### 4.1 One task, one branch

Each task MUST use:

```text
task/<task-id>-<short-description>
```

Example:

```text
task/T005-sqlite-repository
```

Never implement a task directly on `master`.

The branch must start from the current `master`.

### 4.2 Milestone commits

A non-trivial task must be split into meaningful milestones.

After every milestone:

1. targeted tests pass
2. `git diff --check` passes
3. only task-related files are staged
4. a commit is created

Commit format:

```text
<type>(<task-id>): <summary>
```

Examples:

```text
feat(T005): add SQLite schema
feat(T005): implement repository
test(T005): add repository integration tests
```

Never commit known failing tests.

### 4.3 Full verification before completion

Before `[x]`:

```bash
pytest -q
```

must return exit code `0`.

Also run configured:

```bash
ruff check .
ruff format --check .
mypy .
```

### 4.4 Automatic PR creation

After a task is complete:

```text
task branch
 → final tests
 → task state [x]
 → push branch
 → create PR → master
```

PR creation is mandatory when the repository remote and PR tooling are available.

The PR must include:

- task ID
- summary
- milestone commits
- validation results
- acceptance criteria
- architecture impact
- risks

### 4.5 No automatic merge by default

Creating the PR is automatic.

Merging is not automatic unless explicitly authorized by repository policy and the user.

### 4.6 Never fabricate Git results

The agent must never claim:

- a commit exists
- a branch was pushed
- a PR was created
- a PR URL exists

unless the Git/tool output confirms it.

If PR creation is unavailable, report the exact blocker.

## 5. Amendment Process

Architecture or constitution changes must be explicit, documented, and reflected in dependent project documents.
