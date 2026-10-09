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
- [x] **T020** Diarization Port
- [x] **T021** Initial Diarization Adapter

# Phase 3 — Visual Intelligence

- [x] **T022** VLM Port
- [x] **T023** Qwen3-VL Adapter
- [x] **T024** Scene Analysis Prompt
- [x] **T025** Scene Visual Analysis Stage
- [x] **T026** Adaptive Sampling Feedback

# Phase 4 — Movie Knowledge Base

- [x] **T027** Character Repository
- [x] **T028** Character Discovery
- [x] **T029** Character Linking
- [x] **T030** Location Extraction
- [x] **T031** Event Schema/Repository
- [x] **T032** Event Extraction Prompt
- [x] **T033** Event Extraction Stage
- [x] **T034** Evidence Registry
- [x] **T035** Relationship Graph
- [x] **T036** Story Arc Extraction
- [x] **T037** Theme Extraction
- [x] **T038** Twist Detection
- [x] **T039** Build `movie-analysis.json`

# Phase 5 — Review Intelligence

- [x] **T040** Style Profile Loader
- [x] **T041** Review Planner
- [x] **T042** Story Analyst
- [x] **T043** Review Writer Prompt
- [x] **T044** Script Writer
- [x] **T045** Claim Extraction
- [x] **T046** Evidence Retrieval
- [x] **T047** Fact Checker
- [x] **T048** Continuity Checker
- [x] **T049** Script Repair Loop
- [x] **T050** Duration Controller

# Phase 6 — Narration

- [x] **T051** TTS Port
- [x] **T052** Qwen3-TTS Adapter
- [x] **T053** TTS Chunker
- [x] **T054** TTS Concatenation
- [x] **T055** TTS Duration Reconciliation

# Phase 7 — Visual Editing

- [x] **T056** Visual Planner
- [x] **T057** Clip Selector
- [x] **T058** Render Manifest
- [x] **T059** Subtitle Generator
- [x] **T060** Audio Mixer
- [x] **T061** FFmpeg Renderer
- [x] **T062** Render Validation

# Phase 8 — Quality & Benchmark

- [x] **T063** QC Domain Model
- [x] **T064** Evidence Coverage Metric
- [x] **T065** Timeline Consistency Metric
- [x] **T066** Character Consistency Metric
- [x] **T067** Visual Alignment Metric
- [x] **T068** Final Quality Gate
- [x] **T069** Quality Report
- [x] **T070** Stage Retry
- [x] **T071** OOM Recovery
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

# Phase 13 — Desktop App

- [x] **T111** Electron Desktop App

## T111 — Electron Desktop App

**Objective**

Ship a cross-platform desktop GUI (macOS + Windows) that drives the existing
`movie-review` CLI. The app never re-implements the pipeline: it builds the same
CLI arguments a user would type, spawns the CLI as a subprocess, and surfaces
its stdout/stderr live.

**Depends on**: T084 (`process`), T085 (`resume`), T070 (`retry`), T098
(`publish`), T002 (config), T101 (CLI progress reporting).

**Scope**

- `desktop/` Electron app, isolated from `src/movie_review` (no Python added to
  the package, no new runtime dependency for the CLI).
- Main process spawns `uv run movie-review ...` from the repo root.
- Start form exposes every option of `process` plus `resume`, `retry`,
  `publish`, `publish-platforms`.
- Live log console: stderr is parsed into structured entries (JSON
  `log_event` lines and the ASCII progress bar) and streamed to the renderer.
- Progress: current stage, in-stage `WorkProgress` fraction, and per-stage
  status across the 19-stage sequence.
- Stop: terminate the process tree; job state is left resumable.
- Job list from `jobs.db`, plus open-output-folder.
- Settings tab edits `config/default.yaml` and `config/models.yaml`: validated
  with the project's own pydantic settings before writing, timestamped `.bak`
  backup on every write.
- electron-builder targets `dmg` (macOS) and `nsis` (Windows).

**Files**

```text
desktop/package.json
desktop/package-lock.json
desktop/electron-builder.yml
desktop/src/main/main.js
desktop/src/main/preload.js
desktop/src/main/python-runner.js
desktop/src/main/line-parser.js
desktop/src/main/config-store.js
desktop/src/main/jobs-store.js
desktop/src/main/ipc.js
desktop/src/renderer/index.html
desktop/src/renderer/styles.css
desktop/src/renderer/app.js
desktop/test/*.test.js
docs/DESKTOP-APP.md
```

**Acceptance criteria**

- [x] `npm run start` launches the window with no console errors.
- [x] Every `process` option is reachable from the form and maps to the exact
      CLI flag, with the CLI default shown when untouched.
- [x] Clicking Start spawns `uv run movie-review process` with the built argv,
      visible in the app before launch.
- [x] Stderr JSON log lines render as structured log entries, not raw text.
- [x] Stage progress updates while a run is in flight; the 19 stages are listed
      with current/done/failed state.
- [x] Stop terminates the child process tree and reports the exit as cancelled,
      not as a pipeline failure.
- [x] A non-zero CLI exit surfaces the exit code and the last error, and the
      app does not report success.
- [x] Saving `config/default.yaml` or `config/models.yaml` validates through
      pydantic first; a rejected value blocks the write and shows the error.
- [x] Every config write leaves a `.bak.<timestamp>` beside the file.
- [x] Job list renders status/failed_stage/error from `jobs.db`.
- [x] `npm test` passes (59 tests).
- [x] `pytest -q` passes (1207 passed).
- [x] `ruff check .` and `ruff format --check .` pass.
- [x] `mypy` introduces no new errors (see "Known pre-existing failures").

**Required change to the CLI**

`_progress_enabled()` in `src/movie_review/cli/app.py` gated progress on
`sys.stderr.isatty()`. A spawned child always has a pipe on stderr, so the app
would have received no stage lines at all and shown an empty window for hours.
`MOVIE_REVIEW_PROGRESS` now overrides the test in both directions; unset keeps
the original behaviour, so nothing changes for existing users.

**Verification**

| Checked | How |
| --- | --- |
| Window renders, no console errors | `test/screenshot.js`, four tabs captured |
| Real run streams stages and verdicts | `test/e2e-run.js` on a generated 6s clip |
| Stop kills the tree, reports cancelled | `test/e2e-stop.js` on a generated 10min clip |
| Config writes validate, back up, refuse | `tests/unit/test_desktop_bridge.py` (17 tests) |
| argv matches the CLI | `test/argv.test.js` (20 tests) |
| Log parsing matches the CLI format | `test/line-parser.test.js` (27 tests) |
| Spawn prefixes | `test/python-runner.test.js` (8 tests) |

**Known pre-existing failures (not caused by T111)**

- `mypy .` reports 106 errors, all in `tests/` and `scripts/task-state.py`,
  identical in count and file list before and after this task. `mypy src desktop
  tests/unit/test_desktop_bridge.py` is clean.
- `pytest -q` reports 2 failures on a machine with
  `MOVIE_REVIEW_PATHS__DATA_DIR` set in the environment
  (`test_ingest.py::test_context_from_settings`,
  `test_orchestrator.py::test_build_context_uses_jobs_subdirectory`). Both
  reproduce on `09bf05e` with that variable set and pass without it.

**Risks**

- Saving a config re-serialises the YAML, so comments in `config/*.yaml` are not
  preserved. Documented in `docs/DESKTOP-APP.md`; the `.bak` file keeps the
  commented original.
- Stop on Windows is `taskkill /T /F`, because `SIGINT` cannot reach a spawned
  child with no console. The job stays resumable. Documented.

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
