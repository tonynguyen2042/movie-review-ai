# Tasks — movie-review-ai

**Version:** 1.1

## Task State

```text
[ ] not started
[~] in progress
[x] completed
[!] blocked
```

## Mandatory Git Rules

These rules apply to **every task below**.

### 1. One task = one branch

Before implementation:

```bash
git status --short
git checkout master
git pull --ff-only origin master
git checkout -b task/T001-bootstrap-python-project
```

Never implement directly on `master`.

Branch pattern:

```text
task/<task-id>-<short-description>
```

### 2. Milestone commits

Each meaningful milestone must:

1. implement a coherent increment
2. run targeted tests
3. run `git diff --check`
4. stage only relevant files
5. commit

Commit format:

```text
<type>(<task-id>): <summary>
```

### 3. Full test gate

Before `[x]`:

```bash
pytest -q
```

must pass.

Also run configured:

```bash
ruff check .
ruff format --check .
mypy .
```

### 4. Task completion

After all tests and acceptance criteria pass:

1. update task state to `[x]`
2. commit the state change
3. push the task branch
4. create PR into `master`

Do not create a PR while required tests fail.

PR creation is automatic; PR merge is not automatic by default.

### 5. PR template

Every PR should contain:

- task ID
- summary
- milestone commits
- validation
- acceptance criteria
- architecture impact
- risks

Never fabricate a PR URL.

---

# Phase 0 — Foundation

- [x] **T001** Bootstrap Python Project  
  Dependencies: none  
  Deliverable: Python 3.12+ package, pyproject, package layout, dev tooling.

- [x] **T002** Project Configuration  
  Dependencies: T001  
  Deliverable: typed settings, environment overrides, default configuration.

- [x] **T003** Structured Logging  
  Dependencies: T001, T002  
  Deliverable: JSON logging with job/stage context.

- [x] **T004** Domain Models  
  Dependencies: T001  
  Deliverable: Pydantic models for movie, scene, evidence, job, artifact, claims.

- [x] **T005** SQLite Repository  
  Dependencies: T004  
  Deliverable: schema, migrations/bootstrap, repositories.

- [x] **T006** Job State Machine  
  Dependencies: T004, T005  
  Deliverable: persistent job lifecycle and valid state transitions.

- [x] **T007** Artifact Manager  
  Dependencies: T002, T004  
  Deliverable: deterministic artifact paths, hashes, atomic writes, integrity validation.

- [x] **T008** Cache Manager  
  Dependencies: T004, T007  
  Deliverable: cache identity and safe cache lookup/invalidation.

- [x] **T009** CLI Skeleton  
  Dependencies: T002, T006, T007, T008  
  Deliverable: Typer CLI with process/inspect/validate/resume/retry skeleton.

# Phase 1 — Media Intelligence

- [x] **T010** FFmpeg Adapter
- [x] **T011** Media Ingest Stage
- [x] **T012** Proxy Generation
- [x] **T013** PySceneDetect Adapter
- [x] **T014** Scene Detection Stage
- [x] **T015** Frame Sampler

# Phase 2 — Audio Intelligence

- [x] **T016** ASR Port
- [x] **T017** Whisper MLX Adapter
- [x] **T018** Transcript Stage
- [x] **T019** Transcript Normalization
- [ ] **T020** Diarization Port
- [ ] **T021** Initial Diarization Adapter

# Phase 3 — Visual Intelligence

- [ ] **T022** VLM Port
- [ ] **T023** Qwen3-VL Adapter
- [ ] **T024** Scene Analysis Prompt
- [ ] **T025** Scene Visual Analysis Stage
- [ ] **T026** Adaptive Sampling Feedback

# Phase 4 — Movie Knowledge Base

- [ ] **T027** Character Repository
- [ ] **T028** Character Discovery
- [ ] **T029** Character Linking
- [ ] **T030** Location Extraction
- [ ] **T031** Event Schema/Repository
- [ ] **T032** Event Extraction Prompt
- [ ] **T033** Event Extraction Stage
- [ ] **T034** Evidence Registry
- [ ] **T035** Relationship Graph
- [ ] **T036** Story Arc Extraction
- [ ] **T037** Theme Extraction
- [ ] **T038** Twist Detection
- [ ] **T039** Build `movie-analysis.json`

# Phase 5 — Review Intelligence

- [ ] **T040** Style Profile Loader
- [ ] **T041** Review Planner
- [ ] **T042** Story Analyst
- [ ] **T043** Review Writer Prompt
- [ ] **T044** Script Writer
- [ ] **T045** Claim Extraction
- [ ] **T046** Evidence Retrieval
- [ ] **T047** Fact Checker
- [ ] **T048** Continuity Checker
- [ ] **T049** Script Repair Loop
- [ ] **T050** Duration Controller

# Phase 6 — Narration

- [ ] **T051** TTS Port
- [ ] **T052** Qwen3-TTS Adapter
- [ ] **T053** TTS Chunker
- [ ] **T054** TTS Concatenation
- [ ] **T055** TTS Duration Reconciliation

# Phase 7 — Visual Editing

- [ ] **T056** Visual Planner
- [ ] **T057** Clip Selector
- [ ] **T058** Render Manifest
- [ ] **T059** Subtitle Generator
- [ ] **T060** Audio Mixer
- [ ] **T061** FFmpeg Renderer
- [ ] **T062** Render Validation

# Phase 8 — Quality & Benchmark

- [ ] **T063** QC Domain Model
- [ ] **T064** Evidence Coverage Metric
- [ ] **T065** Timeline Consistency Metric
- [ ] **T066** Character Consistency Metric
- [ ] **T067** Visual Alignment Metric
- [ ] **T068** Final Quality Gate
- [ ] **T069** Quality Report
- [ ] **T070** Stage Retry
- [ ] **T071** OOM Recovery
- [ ] **T072** Interrupted Job Recovery
- [ ] **T073** Artifact Integrity
- [ ] **T074** Model Benchmark CLI
- [ ] **T075** Pipeline Benchmark
- [ ] **T076** Memory Benchmark
- [ ] **T077** Balanced Profile

# Phase 9 — Golden Tests

- [ ] **T078** Golden Movie Fixtures
- [ ] **T079** Ground Truth Annotations
- [ ] **T080** Plot Accuracy Evaluation
- [ ] **T081** Hallucination Evaluation
- [ ] **T082** Evidence Coverage Evaluation
- [ ] **T083** Regression Test Runner

# Phase 10 — CLI Completion

- [ ] **T084** `process` Command
- [ ] **T085** `resume`
- [ ] **T086** Stage-Range Execution
- [ ] **T087** `inspect`
- [ ] **T088** `validate`

# Phase 11 — Optional UI

- [ ] **T089** Job Dashboard
- [ ] **T090** Movie Timeline
- [ ] **T091** Character Explorer
- [ ] **T092** Story Graph Viewer
- [ ] **T093** Script Editor
- [ ] **T094** Visual Timeline Editor
- [ ] **T095** QC Report UI

# Phase 12 — Optional Publishing

- [ ] **T096** Metadata Generator
- [ ] **T097** Thumbnail Generator
- [ ] **T098** YouTube Publishing Adapter

---

# Task Execution Rules

## Dependency order

Do not skip task dependencies.

## Scope control

Do not make unrelated changes.

## Schema first

When a task changes a data contract:

```text
schema
→ validation
→ implementation
→ tests
```

## No silent evidence downgrade

Never replace missing evidence with model guesses.

## Artifact preservation

Do not overwrite valid artifacts without version/hash validation.

## Small commits

One meaningful milestone per commit.

## Failure

If a task cannot safely continue:

```text
[!] blocked
```

and report the exact blocker.

## Anti-loop

Before editing, record:

```text
Task:
Files:
Reason:
Expected change:
```

After each edit:

```text
inspect diff
→ targeted tests
→ verify progress
```

If the same file is modified more than 3 times without measurable progress:

```text
STOP
```

Do not create duplicate files such as:

```text
*_new.py
*_v2.py
*_final.py
*_fixed.py
```

## Completion

A task is complete only when:

```text
implementation
→ targeted tests
→ full tests
→ acceptance validation
→ [x]
→ final commit
→ push
→ PR to master
```

No task may be reported as DONE without all required steps.
