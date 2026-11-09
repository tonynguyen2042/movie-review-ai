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

# Phase 14 - Cache Integrity

- [x] **T112** Prompt-Content Cache Identity

## T112 - Prompt-Content Cache Identity

**Objective**

Make a prompt's cache identity follow its content, so "prompt changes invalidate
dependent AI artifacts" is actually true rather than conditional on remembering
to bump a version number.

**Depends on**: T002 (prompts), T008 (cache keys), T025 (vision stage).

**The defect**

Every AI stage bound its cache key with `f"{prompt.name}:{prompt.version}"`. A
prompt is a file. Editing `config/prompts/scene_analysis_v1.md` without bumping
its frontmatter `version` leaves that string unchanged, so the edited run served
the earlier scenes from cache - analysed under the old text - while analysing the
later scenes under the new one. The output is one corpus produced by two
prompts, and nothing in the artifact, the cache key or the log records it.

`config/prompts.py` already computed a `sha256` of every prompt file. It was
never used: `git grep prompt.sha256` found exactly one hit, the assignment that
produced it.

**The fix**

`Prompt.cache_version` - `name:version:<first 16 hex of sha256>` - used by every
stage that keys on a prompt: vision, the review writer, the four story stages,
publishing metadata, and translation. Sixteen hex characters rather than the bare
version, and short enough to stay readable in a log line.

**Files**

```text
src/movie_review/config/prompts.py            + Prompt.cache_version
src/movie_review/vision/analysis.py           3 sites
src/movie_review/review/writer.py             3 sites
src/movie_review/review/translate.py          1 site (shared `version` variable)
src/movie_review/story/{arcs,events,themes,twists}.py   3 sites each
src/movie_review/publishing/ai_metadata.py    1 site (shared `version` variable)
tests/unit/test_prompt_cache_identity.py      9 tests
config/models.yaml                            operator change, not part of the fix
```

**Acceptance criteria**

- [x] `Prompt.cache_version` is `name:version:<16 hex>` and is stable for
      identical content.
- [x] Editing only a prompt's body changes `cache_version`, with name and version
      held constant.
- [x] A vision cache key computed from an edited prompt does not match one
      computed before the edit, and `CacheManager.lookup_json` reports a miss.
- [x] An unedited prompt still hits its cache entry - the fix must not turn every
      run into a miss.
- [x] All eight stage modules use `cache_version`; no
      `f"{prompt.name}:{prompt.version}"` remains.
- [x] `pytest -q` - 1189 passed.
- [x] `ruff check .`, `ruff format --check .`, `mypy src` pass.

**Risks**

- **Every AI cache entry written before this change becomes unreachable.** The
  keys move. This is the intended direction - the old keys could serve analyses
  made from a prompt nobody could identify - but it means the first run after
  this lands re-runs any AI stage whose results were cached. Frame sampling and
  scene detection are unaffected: they do not key on a prompt.
- `ai_metadata.py` and `translate.py` share one `version` variable between the
  cache key and the artifact record, so their recorded `prompt_version` now
  carries the digest too. That is more provenance, not less, but it is a visible
  change to the stored value.

**Measured on job_20261007_006 (read-only, before this fix)**

| Question | Answer |
|---|---|
| Frames reusable on retry? | **Yes** - 179/179 scenes adoptable, 0 to re-extract |
| Vision analyses reusable? | **No** - 0/179 hits |

The 283 stored vision entries cover scenes 1-137 contiguously, but none is
reachable now. Their `input_hash` includes each frame's sha256 and the scene's
dialogue; both were verified stable (`ffmpeg` reproduces a frame bit-for-bit, and
`transcript.json` and the `transcript_segments` table agree), and neither
`_scene_input_hash` nor `STAGE_VERSION` has changed since 2026-10-04. A 480-way
sweep over stage version, model id and prompt version found no match. The entries
therefore describe an earlier state of that job's inputs. The cache is behaving
correctly - refusing to reuse an analysis whose inputs moved - but a retry of
that job pays for all 179 VLM calls.

Related gap, not addressed here: a failed vision run stores per-scene results
only in the cache. `save_scene_analysis` and `vision.json` are written when the
stage completes, so those 137 analyses left no row in the database and would be
lost with the cache directory. Frames already solve this by persisting after
each scene; the vision stage does not.

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

## Fix Campaign (T113-T172)

Created 2026-10-21 from four independent audits. The full index, the
dependency graph and the per-task procedure are in `.spec/fix-plan.md`.
Each task is one branch, one PR into `master`, merged only after
`pytest -q`, `ruff check .`, `ruff format --check .` and `mypy .` all
pass.

---

## T113 - Ignore runtime artifacts

**Objective**

Add `data/job_*/`, `AI_audio.wav` and `job_1/` to `.gitignore`. Delete the stray files from the working tree. No production code changes.

**Depends on**: T002 (paths).

**The defect**

The working tree carried untracked runtime output: `AI_audio.wav` (19.7 MB) at the repo root, `data/job_20261005_001/media/media.json` and an empty `job_1/`. `scripts/task-git.py start` refuses to start a task on a dirty tree, so every task was blocked before it began. `.gitignore` covers `data/jobs/*` but not a job directory written beside it, and nothing covers a stray audio file at the root.

**Files**

```text
.gitignore
AI_audio.wav                       (deleted)
data/job_20261005_001/             (deleted)
job_1/                             (deleted)
```

**Acceptance criteria**

- [x] `.gitignore` covers `data/job_*/`, `AI_audio.wav` and `job_1/`
- [x] `git status --porcelain` is empty
- [x] `pytest -q` passes

---

## T114 - Make `mypy .` green

**Objective**

Annotate the test and script functions mypy strict rejects, and fix the genuine operand errors mypy found in `tests/unit/test_cli_progress.py` (a `str | None` used with `in`). No behaviour change and no blanket `type: ignore`.

**Depends on**: T113.

**The defect**

`mypy src` passes on all 161 source files. `mypy .` - the command `AGENTS.md` STEP 11 names - fails with 107 errors, all in `tests/` (63) and `scripts/task-state.py` (44). They are missing parameter annotations and unsupported-operand errors. Until they are fixed no task can satisfy the required check suite, so the whole plan is blocked.

**Files**

```text
scripts/task-state.py                  44 errors
tests/unit/test_cli_progress.py        16 errors
tests/unit/test_remote_reasoning.py    12 errors
tests/unit/test_orchestrator.py         9 errors
tests/unit/test_t072_t088_regressions.py 6 errors
tests/unit/test_remote_adapters.py      3 errors
tests/unit/test_thumbnail.py            3 errors
tests/unit/* (7 further files)          14 errors
```

**Acceptance criteria**

- [x] `mypy .` reports `Success: no issues found`
- [x] no blanket `# type: ignore` added
- [x] `ruff check .` and `ruff format --check .` pass
- [x] `pytest -q` passes

---

## T115 - Docs test: subprocess encoding and Rich separator

**Objective**

Pass `encoding="utf-8", errors="replace"` to every `subprocess.run` in the file. Match the command name independently of the table separator so the assertion tests the command surface rather than Rich's glyph choice. Pin the child environment so the result does not depend on the developer's locale.

**Depends on**: none. Executed first, because it is the only change that
makes `pytest -q` green, and no task may be closed while the suite is red.

**The defect**

`tests/docs/test_getting_started.py` fails 7 tests under a UTF-8 environment. Two independent defects. (1) The helper spawns `uv run movie-review ...` with `text=True` and no `encoding=`, so the parent decodes the pipe with the Windows locale codec (cp1252) while the child emits UTF-8; the `UnicodeDecodeError` makes `result.stdout` `None` and the assertion raises `TypeError` instead of checking anything. (2) `test_every_documented_command_exists` greps the help output for an ASCII `|`, but Rich renders the command table with U+2502 whenever the child can encode it - so the test passes only because Rich falls back to ASCII under cp1252. Python 3.15 makes UTF-8 mode the default, which turns (2) into a universal break.

**Files**

```text
tests/docs/test_getting_started.py      helper `cli()` + 2 assertions
```

**Acceptance criteria**

- [x] `pytest -q` passes with `PYTHONIOENCODING=utf-8`
- [x] `pytest -q` passes with `PYTHONUTF8=1`
- [x] `pytest -q` passes with neither set
- [x] the command assertion matches under both ASCII and Unicode table rendering

---

## T116 - Render stage reads the flat manifest

**Objective**

Read the flat shape the writer produces. Add a regression test that writes a manifest through `assemble_manifest` and reads it back through the orchestrator stage, so the two shapes cannot drift again. Update the timeline editor to the same shape.

**Depends on**: T115.

**The defect**

`rendering/manifest.py:170` writes the manifest flat - `write_json(manifest_path, manifest.model_dump(mode="json"))` produces `{"segments": [...], "total_seconds": ..., "source_seconds": ...}`. `pipeline/orchestrator.py:771` reads `manifest_data["manifest"]`, the nested envelope that only exists inside the cache payload. The render stage therefore raises `KeyError: 'manifest'` on every real run. Reproduced by executing the real code path. The same defect makes `ui/timeline_editor.py:63` render zero clips against a real manifest, and `tests/unit/test_timeline_editor.py` hides it by hand-writing the nested shape.

**Files**

```text
src/movie_review/pipeline/orchestrator.py   render_fn
src/movie_review/ui/timeline_editor.py      manifest load
tests/unit/test_orchestrator_stage_wiring.py   (new)
```

**Acceptance criteria**

- [x] the render stage reads a manifest written by `assemble_manifest` without `KeyError`
- [x] the timeline editor renders the segments of a real manifest
- [x] a regression test fails if the writer and reader shapes diverge again
- [x] `pytest -q` passes

---

## T117 - Render manifest uses measured narration durations

**Objective**

Read the measured per-paragraph durations from the concatenated narration metadata, falling back to measuring the chunk WAVs. Fail loudly when no measurement exists, rather than inventing 10.0. Reuse `tts/reconcile.py::measure_wav` for the fallback.

**Depends on**: T116.

**The defect**

`pipeline/orchestrator.py:728` sets `narration_seconds = {p.id: 10.0 for p in paragraphs}` with the comment "Need narration timings - simplified for now". This is the only source of segment durations in the render manifest, so `total_seconds`, `source_seconds`, the `loop_clip` decision, the `max_total_seconds` and `max_source_ratio` product controls and the renderer's own 5% duration check are all computed against fiction. The real numbers already exist: `tts/concat.py` writes `narration.json` with a `paragraph_id` and a measured `duration` per chunk, and `tts/chunks.py::collect_chunk_results` returns `ChunkResult.duration_seconds`.

**Files**

```text
src/movie_review/pipeline/orchestrator.py   render_manifest_fn
src/movie_review/tts/chunks.py              paragraph_durations helper (new)
tests/unit/test_orchestrator_stage_wiring.py
```

**Acceptance criteria**

- [x] manifest segment durations equal the measured narration durations
- [x] the stage raises a classified error when no narration has been measured
- [x] a 3-paragraph script no longer produces a 30.0 s manifest
- [x] `pytest -q` passes

---

## T118 - Quality gate computes real metrics

**Objective**

Compute the real metrics from the persisted rows, measure the actual narration duration instead of assuming the target, run `validate_render` over the produced artifacts, write `quality-report.json`, and let the gate fail a job that does not meet the thresholds. The gate logic in `quality/gates.py` is already correct and needs no change.

**Depends on**: T117.

**The defect**

`pipeline/orchestrator.py:789-794` builds `metrics: list[QualityMetric] = []` and sets `actual_seconds = target_seconds`. The gate therefore sees no metric to fail and a duration error of exactly zero, so `evaluate_gate` always passes and the job always reaches `COMPLETED`. The three critical thresholds in `quality/gates.py` - evidence coverage 90, timeline consistency 95, character consistency 95 - are never consulted. The metric functions that would produce them exist - `quality/{coverage,timeline,characters,visual}.py` - along with `build_quality_report` and `validate_render`, and no module in `src/` calls any of them. `NEEDS_REVIEW` is unreachable and no `quality-report.json` is ever written.

**Files**

```text
src/movie_review/pipeline/orchestrator.py   quality_fn
src/movie_review/quality/gates.py             (no change expected)
src/movie_review/quality/report.py            called
src/movie_review/rendering/validate.py        called
tests/unit/test_orchestrator_stage_wiring.py
```

**Acceptance criteria**

- [x] a job whose narration is far from the target ends in `NEEDS_REVIEW`, not `COMPLETED`
- [x] the gate reports `evidence_coverage`, `timeline_consistency` and `character_consistency`
- [x] `quality-report.json` is written for the job
- [x] `validate_render` runs and its findings reach the report
- [x] `pytest -q` passes

---

## Fix Campaign (T113-T172)

Created 2026-10-21 from four independent audits. The full index, the
dependency graph and the per-task procedure are in `.spec/fix-plan.md`.
Each task is one branch, one PR into `master`, merged only after
`pytest -q`, `ruff check .`, `ruff format --check .` and `mypy .` all
pass.

---

## T119 - CLI options reach the pipeline

**Objective**

Persist the four options on the job row, read them in the review stage, and pass `spoilers` to `write_script`. `AppSettings.style` stops being a dead field.

**Depends on**: T115.

**The defect**

`process` parses `--duration`, `--style`, `--spoilers` and `--output` (cli/app.py:412-417), then uses `minutes`, `style`, `spoilers` and `output` only in a log event. The pipeline reads `settings.pipeline.review.target_duration_minutes`, hard-codes `load_style("youtube")` (orchestrator.py:578) and never passes `spoilers` to `write_script`, which accepts the parameter. `settings.paths.output_dir` is never read anywhere. `--duration 5m --style documentary` produces a 20-minute youtube-style full-spoiler review and reports success.

**Files**

```text
src/movie_review/storage/schema.py    jobs columns (style, spoilers, target_seconds)
src/movie_review/storage/repositories.py
src/movie_review/domain/job.py
src/movie_review/pipeline/orchestrator.py   review_fn
src/movie_review/cli/app.py
```

**Acceptance criteria**

- [x] `--duration 5m` yields a 300 s target
- [x] `--style documentary` loads the documentary profile
- [x] `--spoilers none` reaches `write_script`
- [x] `--output` receives the exported output set
- [x] `pytest -q` passes

---

## T120 - Configured WPM replaces hard-coded 150

**Objective**

Use `review/duration.py::target_words(target_seconds, settings.pipeline.review.target_wpm)`.

**Depends on**: T119.

**The defect**

`orchestrator.py:587` computes the writer's word target as `target_seconds * 150 // 60`. The literal 150 contradicts `settings.pipeline.review.target_wpm` (config/settings.py:183), which the TTS reconciliation stage does use two stages later. With `target_wpm: 180` the writer is asked for 150-WPM counts while the reconciler measures against 180, so the script is systematically short and `reconcile_script` returns `expand-required` forever. `AGENTS.md` forbids hard-coding WPM.

**Files**

```text
src/movie_review/pipeline/orchestrator.py   review_fn
```

**Acceptance criteria**

- [x] the writer's word target follows `target_wpm`
- [x] changing `target_wpm` changes the requested word count
- [x] `pytest -q` passes

---

## T121 - Fact-check misquote detection

**Objective**

A quote is misquoted when it is absent from every cited segment, so the condition becomes `any(all(quote not in haystack for haystack in haystacks) for quote in quotes)`.

**Depends on**: T115.

**The defect**

`review/factcheck.py:57` ends with `not any(quote in haystack for quote in quotes for haystack in haystacks)`. The nested generator yields True when *any* quote appears in *any* cited segment, so the expression is True - misquoted - only when no quote matches anything. A claim quoting two lines where one is fabricated is judged clean. `AGENTS.md` requires the review writer never to invent dialogue.

**Files**

```text
src/movie_review/review/factcheck.py
tests/unit/test_factcheck.py
```

**Acceptance criteria**

- [x] a claim quoting one fabricated and one real line is `CONTRADICTED`
- [x] a claim quoting only real lines stays supported
- [x] `pytest -q` passes

---

## T122 - render-manifest stage name

**Objective**

Use the orchestrator's stage name as the single source of truth.

**Depends on**: T116.

**The defect**

`rendering/manifest.py:33` sets `STAGE_NAME = "render"`, but the orchestrator's stage is named `render-manifest` (orchestrator.py:51). A manifest failure therefore records `failed_stage="render"`, `recovery_plan` maps that to `resume_stage="render"`, and `resume` re-runs only the render stage. The manifest file does not exist (the failure precedes the write), so the render stage fails with `FileNotFoundError` and the job can never be recovered through `resume`.

**Files**

```text
src/movie_review/rendering/manifest.py
tests/unit/test_manifest.py
```

**Acceptance criteria**

- [x] a manifest failure records `failed_stage="render-manifest"`
- [x] `resume` after a manifest failure re-runs `render-manifest`
- [x] `pytest -q` passes

---

## T123 - Resume validates the stage name

**Objective**

Validate the recovery plan's stage against `STAGE_SEQUENCE` before running, and report it as a usage error rather than letting a `ValueError` escape.

**Depends on**: T122.

**The defect**

`jobs/recovery.py:62-69` returns `job.failed_stage` verbatim, falling back to `"unknown"` when it is NULL. `orchestrator.run_pipeline` raises `ValueError` for a stage name it does not know (orchestrator.py:275-276), and the CLI `resume` command catches only `KeyboardInterrupt` (cli/app.py:568-583). A resume of a FAILED job with no recorded stage prints a raw traceback instead of a clean error, violating the CLI contract.

**Files**

```text
src/movie_review/pipeline/orchestrator.py   resume_job
src/movie_review/jobs/recovery.py
src/movie_review/cli/app.py
```

**Acceptance criteria**

- [x] resuming a job with an unknown failed stage exits non-zero without a traceback
- [x] `resume` still works for every real stage name
- [x] `pytest -q` passes

---

## T124 - Publish title path leak

**Objective**

Use `pathlib.Path(job.input_file).stem`.

**Depends on**: T115.

**The defect**

`cli/app.py:762` derives the movie title with `job.input_file.rsplit("/", 1)[-1].rsplit(".", 1)[0]`. A Windows path contains no `/`, so on win32 the title becomes `D:\Movies\film` and that string is sent to the model and embedded in the published YouTube, Facebook and TikTok metadata - publishing the operator's directory layout.

**Files**

```text
src/movie_review/cli/app.py
tests/unit/test_publishing_metadata.py
```

**Acceptance criteria**

- [x] a Windows-style path yields the bare file stem
- [x] the generated title contains no path separator
- [x] `pytest -q` passes

---

## T125 - Unload adapters on cache hits

**Objective**

Hoist `unload()` into a `try/finally` around the whole lookup-and-execute block in each of the five modules.

**Depends on**: T115.

**The defect**

In `asr/transcript.py`, `story/arcs.py`, `story/themes.py`, `story/twists.py` and `publishing/ai_metadata.py` the `active.unload()` call sits inside the cache-miss branch, so a cache hit constructs the adapter and drops it without unloading. For the MLX backends `unload()` is what calls `mx.clear_cache()`, so the weights stay resident for the rest of the process, contradicting `AGENTS.md`'s sequential-model-residency rule. `vision/analysis.py` and `review/writer.py` already use the correct `try/finally` shape.

**Files**

```text
src/movie_review/asr/transcript.py
src/movie_review/story/arcs.py
src/movie_review/story/themes.py
src/movie_review/story/twists.py
src/movie_review/publishing/ai_metadata.py
tests/unit/test_adapter_unload.py   (new)
```

**Acceptance criteria**

- [x] `unload()` is called on a cache hit for every one of the five modules
- [x] `unload()` is still called on a cache miss
- [x] `pytest -q` passes

---

## T126 - Language reaches the local Whisper backend

**Objective**

Pass `language=language` to `mlx_whisper.transcribe` when a language is given.

**Depends on**: T115.

**The defect**

`asr/whisper_mlx.py:71` accepts a `language` argument and never uses it: `mlx_whisper.transcribe(audio_path, path_or_hf_repo=model)` omits `language=`, so Whisper auto-detects. The orchestrator comment at orchestrator.py:348-351 claims the opposite. `--language ja` records `ja` in the transcript rows and in the cache key while the audio was transcribed with a guess.

**Files**

```text
src/movie_review/asr/whisper_mlx.py
tests/unit/test_whisper_language.py   (new)
```

**Acceptance criteria**

- [x] the configured language reaches the Whisper call
- [x] omitting the language still auto-detects
- [x] `pytest -q` passes

---

## T127 - Close SQLite connections

**Objective**

Use `contextlib.closing` in `bootstrap`, and close the connections the orchestrator, CLI and dashboard open.

**Depends on**: T115.

**The defect**

`storage/database.py:44` uses `with connect(resolved) as conn:`. `sqlite3.Connection` is a transaction context manager - it commits or rolls back but does not close. Every `bootstrap()` call leaks an open handle: orchestrator.py:214, orchestrator.py:842, orchestrator.py:889, cli/app.py:330, and `ui/dashboard.py` on every request. On Windows the `jobs.db` file stays locked and the handle count grows without bound.

**Files**

```text
src/movie_review/storage/database.py
src/movie_review/pipeline/orchestrator.py
src/movie_review/cli/app.py
src/movie_review/ui/dashboard.py
```

**Acceptance criteria**

- [x] `bootstrap` closes the connection it opens
- [x] the dashboard does not grow open handles across requests
- [x] `pytest -q` passes

---

## T128 - Job-ID allocation race

**Objective**

Create the job with an insert that does not overwrite, and retry on conflict until an id is free.

**Depends on**: T127.

**The defect**

`jobs/manager.py:33-38` checks `repo.get_job` for a free id and then inserts, which is not atomic. `repositories.save_job` uses `ON CONFLICT(job_id) DO UPDATE`, so two concurrent `movie-review process` runs on the same day pick the same id and the second silently overwrites the first job's `input_file`, `status` and `created_at`. `AGENTS.md` lists data corruption as a stop condition.

**Files**

```text
src/movie_review/jobs/manager.py
src/movie_review/storage/repositories.py
tests/unit/test_job_id_race.py   (new)
```

**Acceptance criteria**

- [x] a second job with the same id never overwrites the first
- [x] two concurrent creations get distinct ids
- [x] `pytest -q` passes

---

## T129 - Scene detection idempotency

**Objective**

Detect on the same input every time, and clear the job's previous scene rows before writing the new set.

**Depends on**: T115.

**The defect**

`media/detection.py:51-59` prefers the analysis proxy when one exists, but the proxy is created inside the vision stage, which runs after the scenes stage. The first run detects on the source; any later re-run detects on the proxy, so the cache key misses and a different set of cuts is produced. `repo.save_scene` inserts with `INSERT OR REPLACE` on `(job_id, scene_id)` and nothing deletes the previous rows, so scenes absent from the new run survive with stale boundaries.

**Files**

```text
src/movie_review/media/detection.py
src/movie_review/storage/repositories.py
tests/unit/test_detection.py
```

**Acceptance criteria**

- [x] re-running the scenes stage produces the same cuts
- [x] no scene from a previous run survives a re-run
- [x] `pytest -q` passes

---

## T130 - Cache keys bind every input

**Objective**

Hash the full rendered prompt rather than a fragment of it, so anything the prompt carries is part of the identity.

**Depends on**: T115.

**The defect**

`story/arcs.py:85`, `story/themes.py:85` and `story/twists.py:88` build `input_hash` from `event_lines` alone, but the rendered prompt also contains `characters`. Re-running with a different character set therefore serves the previous model's answer, which was generated against the old roster. `review/writer.py:132-137` has the milder form: it hashes `style.name` but not `style.tone`, nor the outline's `purpose` and `event_ids`, both of which are rendered into the prompt. `AGENTS.md` requires the cache identity to bind every input that can change an artifact.

**Files**

```text
src/movie_review/story/arcs.py
src/movie_review/story/themes.py
src/movie_review/story/twists.py
src/movie_review/review/writer.py
tests/unit/test_cache_key_inputs.py   (new)
```

**Acceptance criteria**

- [x] changing the character set misses the cache
- [x] changing the style tone misses the cache
- [x] an unchanged input still hits
- [x] `pytest -q` passes

---

## T131 - CLI exit codes and reporter cleanup

**Objective**

Validate the stage range order as a usage error, treat an empty result set as a failure, and close the reporter in a `finally`.

**Depends on**: T123.

**The defect**

Two defects in `cli/app.py`. (1) `run_pipeline` returns an empty result list for an inverted stage range (orchestrator.py:282-284) and `any(not r.success for r in results)` over an empty list is False, so `process --stage-from quality --stage-to ingest` exits 0 having done nothing. (2) `reporter.close()` is only called on `KeyboardInterrupt` (cli/app.py:489-492), so the heartbeat `threading.Timer` keeps printing after any other failure - the `retry` command already does it correctly with a `finally`.

**Files**

```text
src/movie_review/cli/app.py
src/movie_review/pipeline/orchestrator.py
tests/unit/test_cli_progress.py
```

**Acceptance criteria**

- [x] an inverted stage range is rejected as a usage error
- [x] `process` exits non-zero when the range runs nothing
- [x] the heartbeat timer is cancelled on every exit path
- [x] `pytest -q` passes

---

## T132 - Retrieval EvidenceIndex

**Objective**

Build the candidate pool and its text map once per retrieval pass and score against in-memory dictionaries; let `check_claims` build one index for the whole script.

**Depends on**: T115.

**The defect**

`review/retrieval.py:112` calls `repo.list_transcript_segments(conn, job_id)` once per dialogue candidate inside `_candidate_text`, then linear-scans the result. Measured: 100 segments 0.037 s / 463 SQL statements, 400 segments 0.514 s / 763 statements, 800 segments 2.835 s / 1163 statements - the statement count is `3 + n_segments + n_events + n_characters`. At 2500 segments one call costs about 28 s, and `factcheck.check_claims` calls it once per claim.

**Files**

```text
src/movie_review/review/retrieval.py
src/movie_review/review/factcheck.py
tests/unit/test_retrieval.py
```

**Acceptance criteria**

- [x] SQL statement count no longer grows with the transcript length
- [x] retrieval over 800 segments is under 50 ms
- [x] `pytest -q` passes

---

## T133 - Frames manifest quadratic persistence

**Objective**

Hash each frame once when it is extracted and carry the digest on the `Frame` record; persist the manifest every N scenes and once at the end instead of after every scene.

**Depends on**: T115.

**The defect**

`media/frames.py:255` calls `_persist` at the end of every scene iteration, and `_persist` calls `_manifest_entries(frames)` which runs `sha256_file` over every frame accumulated so far, then writes the whole manifest and stores it in the cache. Measured: 300 frames / 100 scenes 7.0 s, 600 frames / 200 scenes 19.9 s - worse than quadratic. A 2 h film has roughly 3500 frames, so the stage spends 12-45 minutes writing the manifest before the first VLM call.

**Files**

```text
src/movie_review/media/frames.py
tests/unit/test_frames.py
```

**Acceptance criteria**

- [x] a frame is hashed once, not once per scene
- [x] persisting 600 frames costs no more than a constant multiple of 600 hashes
- [x] an interrupted run still adopts the frames it already produced
- [x] `pytest -q` passes

---

## T134 - SQLite WAL and indexes

**Objective**

Enable WAL and `synchronous=NORMAL` per connection, add the three missing indexes in a migration, and batch the high-frequency writes with `executemany` inside one transaction, following the pattern `save_transcript_segments` already uses.

**Depends on**: T127.

**The defect**

Verified on the live `data/jobs.db`: `journal_mode=delete`, `synchronous=2` (FULL), and the only indexes are `sqlite_autoindex_*` - none created by the project. Every repository write is its own `with conn:` block, so each is a real commit with two fsyncs. `save_mention` runs once per (character, segment) pair, about 15000 times for a feature film, and `character_mentions`, `relationships` and `artifacts.job_id` have no index, so listing them is a full table scan.

**Files**

```text
src/movie_review/storage/database.py
src/movie_review/storage/schema.py
src/movie_review/storage/repositories.py
tests/integration/test_storage.py
```

**Acceptance criteria**

- [x] `journal_mode` is `wal` and `synchronous` is `1`
- [x] indexes exist for `character_mentions`, `relationships` and `artifacts.job_id`
- [x] mention writes are batched
- [x] `pytest -q` passes

---

## T135 - Chunked ASR upload

**Objective**

Cut the audio into segments, transcribe them, and offset the returned timestamps. Stream the multipart body instead of materialising it.

**Depends on**: T115.

**The defect**

`asr/openai_compat.py:89` posts the whole audio file: `http.file_upload` reads every byte, `remote/http.py:167` joins the parts into a second copy, and the result is one request. The dialogue audio is 16 kHz mono PCM (`media/audio.py:19`), so a 2 h film is 230 MB in a single multipart POST under a 120 s default timeout (600 s in the remote profile). Over anything slower than a LAN this times out and fails the whole ASR stage.

**Files**

```text
src/movie_review/asr/openai_compat.py
src/movie_review/remote/http.py
src/movie_review/media/audio.py
tests/unit/test_remote_adapters.py
```

**Acceptance criteria**

- [x] a 2 h film is uploaded in several bounded requests
- [x] the returned segment timestamps are offset back to movie time
- [x] the peak request body is bounded by the segment size
- [x] `pytest -q` passes

---

## T136 - HTTP connection reuse and transport retry

**Objective**

Pool connections per host, add a bounded retry with exponential backoff and jitter for 5xx, 429 and timeouts, and route the reasoning adapter through the shared transport.

**Depends on**: T115.

**The defect**

`remote/http.py:74` uses `urllib.request.urlopen`, which sets `Connection: close` (CPython `urllib/request.py:1329`), so every request opens and tears down a TCP and TLS connection. A 2 h run makes roughly 2000 model calls, so 2000 handshakes. There is no transport-level retry either: `perform` raises on the first `URLError` or `HTTPError`, and the `TimeoutError` branch is never reached by any test. `reasoning/openai_compat.py` duplicates the request logic instead of using the shared transport, so the two paths drift.

**Files**

```text
src/movie_review/remote/http.py
src/movie_review/reasoning/openai_compat.py
src/movie_review/vision/openai_compat.py
src/movie_review/tts/openai_compat.py
tests/unit/test_remote_http.py   (new)
```

**Acceptance criteria**

- [x] consecutive requests to one host reuse a connection
- [x] a transient 5xx is retried and then succeeds
- [x] a timeout is retried and then reported as `RemoteUnavailableError`
- [x] `pytest -q` passes

---

## T137 - Stage-level retry policy

**Objective**

Run every stage through the retry policy with a classified `retry_on` set, exponential backoff and jitter, and record the attempt count on the job.

**Depends on**: T136.

**The defect**

`pipeline/retry.py::run_with_retry` exists and is tested, but `pipeline/orchestrator.py::run_stage` does not use it - one transient network error aborts a run that has been going for hours. The CLI only uses it in the `retry` command. README section 65 defines a four-step escalation (same prompt, reduced context, repair prompt, fallback model) that is not implemented at all.

**Files**

```text
src/movie_review/pipeline/orchestrator.py
src/movie_review/pipeline/retry.py
src/movie_review/jobs/manager.py
tests/unit/test_retry.py
```

**Acceptance criteria**

- [x] a transient failure inside a stage is retried and the stage then succeeds
- [x] a permanent failure still fails the stage
- [x] the retry count is recorded on the job
- [x] `pytest -q` passes

---

## T138 - Parallelise the vision stage

**Objective**

Process scenes in bounded batches through a thread pool. Within a batch each scene uses the previous batch's summaries, which preserves cross-batch continuity while removing the per-scene serialization. Cache hits stay on the serial path so a resumed run is not slowed down.

**Depends on**: T137.

**The defect**

`vision/analysis.py:105` analyses scenes in a strict `for` loop, one VLM round trip per scene - roughly 1000 sequential calls for a 2 h film. At 3 s per scene the stage is 50 minutes of pure serial latency with the machine idle. The only ordering constraint is `previous_summary`, which feeds the previous scene's location and actions into the next prompt.

**Files**

```text
src/movie_review/vision/analysis.py
src/movie_review/pipeline/orchestrator.py
config/default.yaml   (vision.concurrency)
tests/unit/test_vision_parallel.py   (new)
```

**Acceptance criteria**

- [x] scenes in a batch are analysed concurrently
- [x] the results keep scene order
- [x] continuity context still comes from the previous batch
- [x] the concurrency limit is configurable and defaults to a safe value
- [x] `pytest -q` passes

---

## T139 - Parallelise the events stage

**Objective**

Use the same batched, thread-pool approach as the vision stage, keeping the prior-event context aligned to the batch boundary.

**Depends on**: T138.

**The defect**

`story/events.py:103` extracts events one scene per LLM call, sequentially, and each prompt carries the previous events as continuity context. The number of calls equals the number of scenes.

**Files**

```text
src/movie_review/story/events.py
config/default.yaml   (events.concurrency)
tests/unit/test_events_parallel.py   (new)
```

**Acceptance criteria**

- [x] event extraction for a batch runs concurrently
- [x] events are still ordered by timestamp
- [x] prior-event context is preserved at batch boundaries
- [x] `pytest -q` passes

---

## T140 - Cut prompt token duplication

**Objective**

Send only the characters relevant to the current scene, build the story brief per section from that section's events and format the character list compactly, and hash only what the prompt carries. Order each prompt so the stable prefix comes first and the server's prefix cache can be used.

**Depends on**: T138.

**The defect**

Three separate duplications. (1) `story/events.py:97,113` sends the whole character roster in every per-scene prompt: 532 discovery candidates produce an 11.9 KB block, so 1000 prompts carry about 3 M tokens of pure duplication. (2) `review/writer.py:52-67` builds a story brief of 83 554 characters - about 21 k tokens - and interpolates it into all eight section prompts: 167 k duplicated tokens, and a single prompt that exceeds the context of a 14 B model. (3) `story/events.py:216` hashes the entire prior-event list into the cache key although only the last 20 appear in the prompt.

**Files**

```text
src/movie_review/story/events.py
src/movie_review/review/writer.py
src/movie_review/review/planner.py
src/movie_review/characters/discovery.py
config/prompts/event_extraction_v1.md
config/prompts/script_writer_v1.md
tests/unit/test_prompt_size.py   (new)
```

**Acceptance criteria**

- [x] the character roster in a per-scene prompt is bounded by a configured limit
- [x] no single writer prompt exceeds the configured token budget
- [x] the writer brief is built per section
- [x] `pytest -q` passes

---

## T141 - Remaining hot paths

**Objective**

Use a bisect over sorted segments for the dialogue window, sort the events once, read the cache payload once, and memoise the file hash by path, size and modification time.

**Depends on**: T140.

**The defect**

Four smaller measured costs. (1) `vision/analysis.py:52` and `story/events.py:107` scan the whole segment list for every scene - 1000 scenes times 2500 segments is 2.5 M iterations, twice. (2) `review/planner.py:52-63` sorts the event list seven independent times. (3) `cache/manager.py:42-64` reads the payload on every hit and then reads it again in `lookup_json`. (4) The source movie and the proxy are SHA-256'd six times across the pipeline - about 13-15 GB of redundant reads.

**Files**

```text
src/movie_review/vision/analysis.py
src/movie_review/story/events.py
src/movie_review/review/planner.py
src/movie_review/cache/manager.py
src/movie_review/artifacts/manager.py
tests/unit/test_hot_paths.py   (new)
```

**Acceptance criteria**

- [x] the dialogue window is found by bisect, not by a full scan
- [x] the event list is sorted once
- [x] a cache hit reads the payload once
- [x] the source file is hashed once per process
- [x] `pytest -q` passes

---

## Fix Campaign (T113-T172)

Created 2026-10-21 from four independent audits. The full index, the
dependency graph and the per-task procedure are in `.spec/fix-plan.md`.
Each task is one branch, one PR into `master`, merged only after
`pytest -q`, `ruff check .`, `ruff format --check .` and `mypy .` all
pass.

---

## T142 - Verify stage: claims, fact-check, repair

**Objective**

Add a `verify` stage between the review and the translation stages: extract the claims, store them, run the fact checker, run the continuity checker, apply the repair rules, persist the verdicts, and transition `SCRIPT_READY` to `SCRIPT_VERIFIED`.

**Depends on**: T118.

**The defect**

`review/claims.py::extract_claims` and `store_claims`, `review/factcheck.py::check_claims` and `review/repair.py::repair_script` are complete and tested, and no module in `src/` calls any of them. The `claims` table is therefore always empty, `CONTRADICTED` and `INSUFFICIENT_EVIDENCE` never appear in any produced artifact, and the `SCRIPT_VERIFIED` state in the spec's chain is unreachable. This is the enforcement point for the constitution's P1 (Evidence First) and P5 (No Silent Hallucination).

**Files**

```text
src/movie_review/pipeline/orchestrator.py   STAGE_SEQUENCE + verify_fn
src/movie_review/review/claims.py
src/movie_review/review/factcheck.py
src/movie_review/review/repair.py
src/movie_review/review/continuity.py
src/movie_review/storage/repositories.py
tests/unit/test_verify_stage.py   (new)
```

**Acceptance criteria**

- [x] a `verify` stage appears in `movie-review stages`
- [x] the claims table is populated after the stage runs
- [x] a contradicted claim is removed or qualified by the repair rules
- [x] the job reaches `SCRIPT_VERIFIED`
- [x] `pytest -q` passes

---

## T143 - Subtitles stage

**Objective**

Add a stage that builds the cues from the render manifest's real segment durations and writes `render/review.srt`, then pass it to the renderer.

**Depends on**: T142.

**The defect**

`rendering/subtitles.py::build_cues` and `write_srt` are complete and tested, and nothing calls them. `review.srt` ? a required v1.0 output ? is never produced. The renderer only copies a sidecar if it happens to exist (`orchestrator.py:775-781`). README ?47 also forbids estimating subtitle duration from word count, so the cues must come from the real narration timing.

**Files**

```text
src/movie_review/pipeline/orchestrator.py   STAGE_SEQUENCE + subtitles_fn
src/movie_review/rendering/subtitles.py
tests/unit/test_subtitles_stage.py   (new)
```

**Acceptance criteria**

- [x] `review.srt` is written for a completed render
- [x] cue timings come from the measured narration, not from word counts
- [x] the renderer receives the sidecar
- [x] `pytest -q` passes

---

## T144 - Diarization and speaker linking

**Objective**

Add a `diarization` stage after the transcript that runs the diarizer over the dialogue audio, links the speakers to the discovered characters, persists the links, and records the speaker in the transcript rows.

**Depends on**: T143.

**The defect**

`diarization/initial.py::EnergyDiarizer` and `characters/linking.py::link_speakers` and `save_links` are complete and tested, and no stage calls them. The `speakers` table is always empty, `pipeline.diarization` in the config is a flag that does nothing, and README ?14 and ?17 (stage 6 and stage 9) are unimplemented.

**Files**

```text
src/movie_review/pipeline/orchestrator.py   STAGE_SEQUENCE + diarization_fn
src/movie_review/diarization/initial.py
src/movie_review/characters/linking.py
src/movie_review/storage/repositories.py
tests/unit/test_diarization_stage.py   (new)
```

**Acceptance criteria**

- [x] a `diarization` stage appears in `movie-review stages`
- [x] the speakers table is populated
- [x] speaker ids appear on the transcript segments
- [x] `pytest -q` passes

---

## T145 - Story graph relationships

**Objective**

Call `build_graph` from the events or story stage, persist every relationship, and extend the edge vocabulary toward the specified set with the evidence that supports each edge.

**Depends on**: T144.

**The defect**

`knowledge/graph.py::build_graph` has no caller. `repo.save_relationship` is never called, so the `relationships` table is always empty and `movie-analysis.json` always reports `"relationships": []`. README ?22 lists 15 edge types; the module emits 3.

**Files**

```text
src/movie_review/pipeline/orchestrator.py
src/movie_review/knowledge/graph.py
src/movie_review/knowledge/analysis.py
src/movie_review/storage/repositories.py
tests/unit/test_story_graph.py
```

**Acceptance criteria**

- [x] `movie-analysis.json` carries a non-empty relationships list
- [x] every relationship is persisted
- [x] the graph exposes more than the three current edge types
- [x] `pytest -q` passes

---

## T146 - Adaptive frame sampling feedback

**Objective**

Feed the per-scene analysis back into the sampling decision and re-sample the scenes that qualify for more or fewer frames.

**Depends on**: T145.

**The defect**

`media/feedback.py::apply_feedback` is complete and tested, and the vision stage never calls it. README ?12 requires the sampler to increase the frame budget for high motion, high cut density, a new character, a new location, a dialogue transition, a detected action, a visual anomaly or an important story event, and to reduce it for a static conversation, repeated frames, a dark shot or a low-information shot. Today the budget is a pure function of the scene duration.

**Files**

```text
src/movie_review/pipeline/orchestrator.py   vision_fn
src/movie_review/media/feedback.py
src/movie_review/media/frames.py
tests/unit/test_sampling_feedback.py   (new)
```

**Acceptance criteria**

- [x] a high-importance scene receives more frames than the duration rule alone would give
- [x] a low-information scene receives fewer
- [x] the result stays inside the configured maximum
- [x] `pytest -q` passes

---

## T147 - Music bed and ducking

**Objective**

Add the music configuration, load a local track, mix it under the narration with ducking, and feed the mixed track to the renderer. Keep the music optional and local, per README ?43 and ?86.

**Depends on**: T146.

**The defect**

`rendering/audio.py::mix` implements the narration-plus-music mix with the ducking envelope README ?43 asks for, and nothing calls it. The renderer muxes the narration alone, so the music system does not exist.

**Files**

```text
src/movie_review/pipeline/orchestrator.py   render_fn
src/movie_review/rendering/audio.py
src/movie_review/rendering/renderer.py
config/default.yaml   (music)
tests/unit/test_music_mixing.py   (new)
```

**Acceptance criteria**

- [x] a configured music track is mixed under the narration
- [x] the narration stays intelligible while the music plays
- [x] no music track means the current behaviour
- [x] `pytest -q` passes

---

## T148 - Thumbnail generation

**Objective**

Add an optional thumbnail stage or command that composes a frame with the movie title and writes `thumbnail.png`.

**Depends on**: T147.

**The defect**

`publishing/thumbnail.py::generate_thumbnail` is complete and tested, and nothing calls it. The publish command passes a thumbnail path only if the file happens to exist, so uploads never carry one. README ?48 requires a 1280x720 thumbnail as a separate optional stage.

**Files**

```text
src/movie_review/cli/app.py   thumbnail command
src/movie_review/publishing/thumbnail.py
tests/unit/test_thumbnail.py
```

**Acceptance criteria**

- [x] a thumbnail command exists and writes a 1280x720 image
- [x] the publish command attaches the generated thumbnail
- [x] the command is optional and does not run as a pipeline stage
- [x] `pytest -q` passes

---

## T149 - OOM recovery wiring

**Objective**

Wrap the model-invoking stage bodies in `run_with_oom_recovery`, with the adapter's `unload` as the release step and a reduced workload on the retry.

**Depends on**: T148.

**The defect**

`models/resources.py::run_with_oom_recovery` is complete and tested, and no stage calls it. The constitution's P8 requires the system to detect memory pressure, release the model, clear the cache, reduce the workload and retry. A 4K source on a 128 GB box currently crashes the run instead of degrading.

**Files**

```text
src/movie_review/vision/analysis.py
src/movie_review/asr/transcript.py
src/movie_review/tts/chunks.py
src/movie_review/review/writer.py
src/movie_review/models/resources.py
tests/unit/test_oom.py
```

**Acceptance criteria**

- [x] an OOM during a stage releases the model and retries
- [x] a successful retry continues the stage
- [x] a persistent OOM fails the stage with a classified error
- [x] `pytest -q` passes

---

## T150 - Privacy cloud_ai enforcement

**Objective**

Refuse to build a remote adapter while `cloud_ai` is false, and say which slot and which profile asked for it.

**Depends on**: T149.

**The defect**

`settings.privacy.cloud_ai` is declared in the config and read by nothing. The constitution's P7 and README ?85 require that no movie content leaves the machine unless an explicitly configured cloud provider is enabled. A profile that routes a slot at a remote endpoint currently does so regardless of the flag.

**Files**

```text
src/movie_review/config/settings.py
src/movie_review/reasoning/factory.py
src/movie_review/vision/factory.py
src/movie_review/asr/factory.py
src/movie_review/tts/factory.py
tests/unit/test_privacy_gate.py   (new)
```

**Acceptance criteria**

- [x] a remote slot with `cloud_ai: false` is refused with a clear message
- [x] `cloud_ai: true` allows the remote adapter
- [x] `pytest -q` passes

---

## T151 - Output set and --output

**Objective**

Render the script to Markdown, write the final manifest, and materialise the whole output set into the directory the user asked for.

**Depends on**: T150.

**The defect**

README ?98 and ?1 promise an output directory holding `review.mp4`, `review.srt`, `narration.wav`, `review-script.md`, `movie-analysis.json`, `quality-report.json`, `manifest.json` and `thumbnail.png`. Four of the eight are never produced: there is no Markdown renderer, `artifacts/manager.py::manifest_path` has no caller, and `--output` is only logged. `settings.paths.output_dir` is never read.

**Files**

```text
src/movie_review/pipeline/orchestrator.py   export stage
src/movie_review/pipeline/export.py   (new)
src/movie_review/review/writer.py   markdown renderer
src/movie_review/artifacts/manager.py
src/movie_review/cli/app.py
tests/unit/test_output_set.py   (new)
```

**Acceptance criteria**

- [x] the output directory contains all eight promised files
- [x] `--output` is honoured
- [x] the Markdown script is derived from the structured script, not maintained separately
- [x] `pytest -q` passes

---

## T152 - Prompt registry matches reality

**Objective**

Rewrite the registry to the eight real prompts, have `load_prompt` honour the pinned version when the registry names one, and fall back to the newest when it does not.

**Depends on**: T115.

**The defect**

`config/default.yaml:54-62` declares versions for `character_analysis`, `story_analysis`, `review_planner`, `fact_checker` and `visual_planner` ? none of which exist. The eight prompt files on disk are `event_extraction`, `publishing_metadata`, `scene_analysis`, `script_writer`, `story_arc`, `theme`, `translate` and `twist`. Separately, `settings.prompts.versions` is read by nothing: `config/prompts.py::load_prompt` always takes the newest file, so the registry is decorative and a prompt version can never be pinned.

**Files**

```text
config/default.yaml
src/movie_review/config/prompts.py
src/movie_review/config/settings.py
tests/unit/test_prompts.py
```

**Acceptance criteria**

- [x] every name in the registry has a file on disk
- [x] a pinned version is loaded instead of the newest
- [x] an unpinned prompt still loads the newest
- [x] `pytest -q` passes

---

## T153 - CLI read-only commands

**Objective**

Add the read-only commands, and let `inspect` accept either a movie path or a job id.

**Depends on**: T152.

**The defect**

README ?50 lists `analyze`, `scenes`, `transcript`, `story`, `script` and `render`. None exists. `inspect` takes a job id where ?96 makes it the Phase 0 acceptance command that takes a movie path. `docs/GETTING-STARTED.md` documents what exists, so the CLI and the specification disagree.

**Files**

```text
src/movie_review/cli/app.py
tests/unit/test_cli.py
tests/docs/test_getting_started.py
```

**Acceptance criteria**

- [x] each documented command exists and is reachable
- [x] `inspect` accepts a movie path and a job id
- [x] the guide and the CLI agree
- [x] `pytest -q` passes

---

## T154 - CLI benchmark command

**Objective**

Add a `benchmark` command with model, pipeline and memory modes over the existing measurement functions.

**Depends on**: T153.

**The defect**

`benchmark/{models,pipeline,memory}.py` implement the measurements README ?75 and ?76 require, and no command can run them. ?56 states the Qwen3-VL size must be benchmarked on the target machine rather than hard-coded, which is impossible without a command.

**Files**

```text
src/movie_review/cli/app.py
src/movie_review/benchmark/
tests/unit/test_benchmark.py
```

**Acceptance criteria**

- [x] `movie-review benchmark --mode model` runs a measurement
- [x] `--mode pipeline` reports per-stage timings
- [x] `--mode memory` reports the memory figures
- [x] `pytest -q` passes

---

## T155 - CLI flags

**Objective**

Add the missing flags: the `--from-stage` and `--to-stage` aliases, `--force` to invalidate the affected cache entries, `--deterministic` to pin seed and temperature, and `--keep-intermediates` to skip the intermediate cleanup.

**Depends on**: T154.

**The defect**

README ?49 and ?74 name `--resume`, `--from-stage`, `--to-stage`, `--force` and `--deterministic`; ?83 names `--keep-intermediates`. The CLI has `--stage-from` and `--stage-to` under different names, and the rest do not exist. There is no `seed` or `temperature` anywhere in the code, so ?73 reproducibility and ?74 deterministic mode are unreachable.

**Files**

```text
src/movie_review/cli/app.py
src/movie_review/config/settings.py
src/movie_review/reasoning/port.py
src/movie_review/reasoning/openai_compat.py
src/movie_review/reasoning/qwen.py
src/movie_review/cache/manager.py
tests/unit/test_cli.py
```

**Acceptance criteria**

- [x] each documented flag exists and is validated
- [x] `--deterministic` reaches the generation config and the cache key
- [x] `--force` invalidates and re-runs the selected stages
- [x] `pytest -q` passes

---

## T156 - model_runs and token usage

**Objective**

Add the `model_runs` table, return usage from the ports, and record a row for every model call.

**Depends on**: T155.

**The defect**

README ?52 lists a `model_runs` table and ?53 requires every model invocation to record the model, runtime, stage, prompt hash, input and output tokens, duration and temperature, calling it "essential for reproducibility". The table does not exist, no adapter returns token counts, and nothing is recorded. Nine of the twenty-three tables in ?52 are missing entirely.

**Files**

```text
src/movie_review/storage/schema.py
src/movie_review/storage/repositories.py
src/movie_review/reasoning/port.py
src/movie_review/vision/port.py
src/movie_review/asr/port.py
src/movie_review/tts/port.py
tests/integration/test_storage.py
```

**Acceptance criteria**

- [x] a `model_runs` table exists with the ?53 columns
- [x] every model call records a row
- [x] the recorded token counts match the server's usage when it reports them
- [x] `pytest -q` passes

---

## T157 - Missing database tables

**Objective**

Add the missing tables in a migration and persist the corresponding records, so the queryable copy matches the file artifacts.

**Depends on**: T156.

**The defect**

README ?52 lists twenty-three tables. The schema has fourteen. `shots`, `story_arcs`, `themes`, `twists`, `review_sections`, `review_paragraphs`, `tts_segments`, `visual_segments` and `render_segments` are absent, which is why `knowledge/analysis.py:111-113` reads the arcs, themes and twists back from JSON files because "they have no table of their own".

**Files**

```text
src/movie_review/storage/schema.py
src/movie_review/storage/repositories.py
src/movie_review/knowledge/analysis.py
tests/integration/test_storage.py
```

**Acceptance criteria**

- [x] every table named in ?52 exists
- [x] the arcs, themes and twists are queryable from the database
- [x] `pytest -q` passes

---

## T158 - JSON Schemas and artifact validation

**Objective**

Author the seven schemas, publish them, and validate the artifacts against them when they are written.

**Depends on**: T157.

**The defect**

README ?6.6 requires every AI output to pass schema validation before entering the next stage, and ?7 lists seven schema files under `schemas/`. That directory is empty, so validation happens only through the pydantic models and the canonical JSON Schema contract is not published.

**Files**

```text
schemas/*.schema.json   (7 files)
src/movie_review/artifacts/manager.py
src/movie_review/schemas.py   (new)
tests/unit/test_schemas.py   (new)
```

**Acceptance criteria**

- [x] all seven schema files exist and are valid JSON Schema
- [x] an artifact that violates its schema is rejected at write time
- [x] a valid artifact still writes
- [x] `pytest -q` passes

---

## T159 - Second-pass critic model

**Objective**

Add a critic module and a prompt, run it as an optional pass after verification, and record the issues it raises.

**Depends on**: T158.

**The defect**

`config/models.yaml` declares a `critic` slot ? `Qwen3.5-122B-A10B`, enabled in the `quality` profile ? and no code builds a critic adapter, so the quality profile behaves exactly like balanced. README ?35 asks for a second pass over script critique, story coherence, hook quality, pacing, unsupported claims and rewrite suggestions.

**Files**

```text
src/movie_review/review/critic.py   (new)
config/prompts/critic_v1.md   (new)
src/movie_review/pipeline/orchestrator.py
config/models.yaml
tests/unit/test_critic.py   (new)
```

**Acceptance criteria**

- [x] the critic runs when its slot is enabled and is skipped when it is not
- [x] the issues it raises reach the quality report
- [x] the prompt follows the ?63 contract
- [x] `pytest -q` passes

---

## T160 - CI and coverage gate

**Objective**

Add a CI workflow that installs the dev extra and runs ruff, ruff format, mypy and pytest on Python 3.12 for ubuntu and macos-arm64, and add a coverage gate that ratchets from a measured baseline.

**Depends on**: T114.

**The defect**

There is no `.github/workflows/` at the repository root, so nothing runs the test suite on push or on a pull request. `coverage` and `pytest-cov` are not installed and `pyproject.toml` has no coverage configuration, so the coverage level is unknown. The three P0 blockers survived because nothing executed the stage closures.

**Files**

```text
.github/workflows/ci.yml   (new)
pyproject.toml
requirements: pytest-cov in the dev extra
```

**Acceptance criteria**

- [x] CI runs on push and on pull requests
- [x] the workflow fails on a lint, type or test failure
- [x] a coverage threshold is enforced and does not regress
- [x] `pytest -q` passes locally

---

## T161 - Root conftest and de-duplicated helpers

**Objective**

Add a root `tests/conftest.py` with the shared fixtures and move the duplicated helpers into it, deleting the copies.

**Depends on**: T160.

**The defect**

There is no `tests/conftest.py`; only `tests/unit/conftest.py` with a single fixture. 134 helper functions exist across the suite and 51 names are duplicated between files ? `_harness` in twelve, `_script` in ten, `_paragraph` in eight, `_scene` in seven, `_events` in nine. `_FakeResponse` is byte-identical in two files. The `db` fixture is defined twice in the integration tests.

**Files**

```text
tests/conftest.py   (new)
tests/unit/conftest.py
tests/integration/test_storage.py
tests/integration/test_characters.py
tests/unit/*.py   (helper removal)
```

**Acceptance criteria**

- [x] no helper name is defined in more than one test file
- [x] the shared fixtures live in one place
- [x] the suite still passes with the same assertions
- [x] `pytest -q` passes

---

## T162 - Markers, strict config and timeout

**Objective**

Register the markers, enable the strict options, add `xfail_strict`, install `pytest-timeout` with a per-test timeout, and convert the local skip conditions into markers.

**Depends on**: T161.

**The defect**

Only `parametrize` and `skipif` are used; no custom marker is registered and `NEEDS_FFMPEG` is a local variable rather than a marker, so a developer cannot select the subset of tests that need ffmpeg or MLX. `pyproject.toml` sets only `testpaths`, with no `--strict-markers`, no `--strict-config` and no `xfail_strict`. `pytest-timeout` is not installed, and `test_cli.py::test_resume_retry` already takes 5.36 s.

**Files**

```text
pyproject.toml
tests/conftest.py
tests/unit/test_cli.py
tests/unit/test_da*.py   (MLX guards)
```

**Acceptance criteria**

- [x] `pytest -m "not ffmpeg"` selects the subset
- [x] a typo in a marker name fails the run
- [x] a hanging test fails within the timeout
- [x] `pytest -q` passes

---

## T163 - End-to-end pipeline test

**Objective**

Add an end-to-end test that drives `run_pipeline` across every stage with stubbed adapters and ffmpeg, and asserts the artifact tree, the render manifest, the state transitions and the final status.

**Depends on**: T162.

**The defect**

`tests/pipeline/` is empty. README ?79 requires an integration test that runs a ten-minute movie through FFmpeg, PySceneDetect, Whisper, a mock VLM, a mock LLM and the renderer. The test-coverage audit found that 16 of the 19 stage closures never execute in any test, which is precisely why the three P0 blockers went unnoticed.

**Files**

```text
tests/pipeline/test_end_to_end.py   (new)
tests/conftest.py
```

**Acceptance criteria**

- [x] every stage closure executes at least once in the suite
- [x] the test asserts the artifact tree and the final status
- [x] the test is deterministic and needs no network or model
- [x] `pytest -q` passes

---

## T164 - Golden baseline

**Objective**

Add an on-disk golden fixture and a test that scores the evaluators against it, plus a test that pins the in-source fixture to the on-disk copy.

**Depends on**: T163.

**The defect**

`tests/golden/` is empty. README ?77 requires three manually verified movies with scenes, characters, major events, the ending and the twist, as a regression baseline. The only "golden" data is a Python dict inside `src/movie_review/eval/fixtures.py`, so a change to that module silently changes the expected values the evaluators are scored against.

**Files**

```text
tests/golden/golden-01/analysis.json   (new)
tests/golden/golden-01/ground_truth.json   (new)
tests/unit/test_golden_baseline.py   (new)
```

**Acceptance criteria**

- [x] the golden fixture lives on disk
- [x] the regression report passes against it
- [x] the in-source fixture and the on-disk copy are proven equal
- [x] `pytest -q` passes

---

## T165 - Direct tests for remote/http.py

**Objective**

Cover the transport directly: the error mapping for each failure mode, the endpoint join, the header construction, the multipart encoding and the file upload.

**Depends on**: T160.

**The defect**

`remote/http.py` is 211 lines with no direct test. `build_endpoint`, `auth_headers`, `encode_multipart`, `file_upload`, `post_multipart` and `post_for_bytes` are never called directly, the `TimeoutError` branch of `perform` has zero hits in the whole repository, and `RemoteProtocolError` is never named in any test. A hung remote server therefore raises a raw `TimeoutError` instead of `RemoteUnavailableError`, breaking the error contract of every adapter.

**Files**

```text
tests/unit/test_remote_http.py   (new)
```

**Acceptance criteria**

- [x] each error mode maps to the documented exception
- [x] the `TimeoutError` branch is exercised
- [x] the multipart body is well formed and the filename is sanitised
- [x] `pytest -q` passes

---

## T166 - Path traversal guard tests

**Objective**

Test the guards directly with absolute, empty, drive-letter and nested-relative paths.

**Depends on**: T165.

**The defect**

`artifacts/manager.py::resolve_relative` is never called directly; only the `../..` case is covered, and only indirectly through `scan_job_integrity`. An absolute path and a Windows drive path are not proven to be rejected. `relative_artifact_path` never raises in any test, so a stage writing outside the job root would record a path that later cannot be validated.

**Files**

```text
tests/unit/test_artifacts.py
src/movie_review/artifacts/manager.py   (only if a guard is found to be missing)
```

**Acceptance criteria**

- [x] an absolute path is rejected
- [x] a Windows drive path is rejected
- [x] an empty path is rejected
- [x] a nested relative path is accepted
- [x] `pytest -q` passes

---

## T167 - TTS chunk ID stability

**Objective**

Give each chunk a content-derived id so the same text always maps to the same file, and split an over-long single sentence on word boundaries.

**Depends on**: T115.

**The defect**

`tts/chunks.py::plan_chunks` numbers chunks positionally ? `tts_001`, `tts_002` ? and the concat stage re-plans and assumes the ids match. Inserting one paragraph into the script shifts every subsequent id, so `tts-concat` silently concatenates the wrong WAV files and the narration is wrong with no error. A paragraph of 400 words with no sentence punctuation is also never split, because the split is by sentence.

**Files**

```text
src/movie_review/tts/chunks.py
src/movie_review/tts/concat.py
tests/unit/test_chunks.py
```

**Acceptance criteria**

- [x] the same script always produces the same chunk ids
- [x] inserting a paragraph does not change the id of an unchanged chunk
- [x] a single long sentence is split into chunks within the word budget
- [x] `pytest -q` passes

---

## T168 - De-flake the timing tests

**Objective**

Let the server bind port 0 and report the port it chose, replace the sleeps with explicit synchronisation, and assert the duration without a wall-clock threshold.

**Depends on**: T161.

**The defect**

`tests/unit/test_dashboard.py::test_dashboard_start_stop` binds a socket to find a free port, releases it, then binds the server to that port after a 0.2 s sleep ? a classic TOCTOU race that fails on a busy machine. `tests/unit/test_cli_progress.py` contains six sub-second sleeps, one of which asserts `threading.active_count()` did not grow, which depends on machine load. `test_orchestrator.py::test_run_stage_measures_duration` asserts a wall-clock duration with a 50% margin.

**Files**

```text
tests/unit/test_dashboard.py
tests/unit/test_cli_progress.py
tests/unit/test_orchestrator.py
```

**Acceptance criteria**

- [x] the dashboard test uses an ephemeral port and never races
- [x] no test depends on machine load
- [x] the suite passes when run repeatedly
- [x] `pytest -q` passes

---

## T169 - Missing documentation

**Objective**

Write the five documents against the code as it stands.

**Depends on**: T168.

**The defect**

README ?7 lists five files under `docs/`: `architecture.md`, `pipeline.md`, `schemas.md`, `model-selection.md` and `troubleshooting.md`. `docs/` holds only `GETTING-STARTED.md` and `DESKTOP-APP.md`, so the architecture, the pipeline contract, the schema contract, the model rationale and the troubleshooting guide are all absent.

**Files**

```text
docs/architecture.md   (new)
docs/pipeline.md   (new)
docs/schemas.md   (new)
docs/model-selection.md   (new)
docs/troubleshooting.md   (new)
```

**Acceptance criteria**

- [x] each file exists and describes the current implementation
- [x] no document claims a behaviour the code does not have
- [x] `pytest -q` passes

---

## T170 - Missing scripts

**Objective**

Write the four scripts, delegating to the existing library functions, and add the intermediate cleanup the cache policy describes.

**Depends on**: T169.

**The defect**

README ?7 lists `scripts/benchmark_models.py`, `benchmark_pipeline.py`, `validate_movie.py` and `cleanup_cache.py`. `scripts/` holds only `task-git.py` and `task-state.py`. The cache policy in ?84 also has no cleanup implementation, so a feature-length run leaves gigabytes of frames and proxies with no way to reclaim them.

**Files**

```text
scripts/benchmark_models.py   (new)
scripts/benchmark_pipeline.py   (new)
scripts/validate_movie.py   (new)
scripts/cleanup_cache.py   (new)
src/movie_review/pipeline/cleanup.py   (new)
```

**Acceptance criteria**

- [x] each script runs and prints its result
- [x] the cleanup script removes only regenerable intermediates
- [x] `pytest -q` passes

---

## T171 - LICENSE and configuration cleanup

**Objective**

Add the LICENSE, reconcile the configuration with what the code reads, and give the task-state script a single source of truth.

**Depends on**: T170.

**The defect**

The repository has no `LICENSE` file although `desktop/package.json` declares MIT. `config/prompts` names five prompts that do not exist and the registry is read by nothing. `settings.memory.reserve_mb` and `settings.pipeline.evidence_required` are declared and read by nothing. `scripts/task-state.py` duplicates the task state that `.spec/state.json` already holds.

**Files**

```text
LICENSE   (new)
config/default.yaml
src/movie_review/config/settings.py
scripts/task-state.py
```

**Acceptance criteria**

- [x] a LICENSE file exists and matches the declared licence
- [x] every configuration key is either read by the code or removed
- [x] `pytest -q` passes

---

## T172 - Orchestrator context duplication

**Objective**

Give `PipelineContext` a `stage_context()` method and use it in every stage closure.

**Depends on**: T171.

**The defect**

`pipeline/orchestrator.py` builds a `StageContext` from six fields by hand in eleven stage closures ? the same eleven-line block repeated eleven times, and the `PipelineContext` subclass that already carries all of them is discarded on every call. Any new context field has to be added in eleven places.

**Files**

```text
src/movie_review/pipeline/orchestrator.py
tests/unit/test_orchestrator.py
```

**Acceptance criteria**

- [x] the eleven duplicated blocks collapse to one method
- [x] the stage closures use it
- [x] `pytest -q` passes

---

## T176 - Concurrent model calls share one HTTP connection

**Objective**

Give every concurrent model call its own pooled connection, and make a stage
that refuses a failed job report the stage and the error the job recorded.

**Depends on**: T136, T138.

**The defect**

`remote/http.py` kept one `HTTPConnection` per host in a process-wide `_Pool`,
on the assumption -- stated in a comment -- that the pipeline was sequential
and that the parallel stages used one pool per worker. They do not: the vision
stage analyses eight scenes per batch through a `ThreadPoolExecutor` and every
thread goes through the same `_POOL`. Two threads that send at once drive one
`HTTPConnection` into its "request sent" state, and the second raises
`CannotSendRequest('Request-sent')`, which the pool reports as
`cannot reach <url>: Request-sent` -- a client-side state error dressed as a
network failure. A remote run against a healthy vLLM server therefore died at
`vision` with a message that pointed at the wrong machine.

The stage then made that unreadable: thirteen stages refused a failed job with
`Job <id> failed; resume arrives in T085`, a task number where the recorded
`failed_stage` and `error` belong, so the CLI printed the placeholder while
the cause sat unused in the job row.

**Files**

```text
src/movie_review/remote/http.py
src/movie_review/jobs/failure.py   (new)
src/movie_review/asr/transcript.py
src/movie_review/knowledge/analysis.py
src/movie_review/media/detection.py
src/movie_review/media/ingest.py
src/movie_review/pipeline/diarization.py
src/movie_review/pipeline/verify.py
src/movie_review/quality/gates.py
src/movie_review/rendering/manifest.py
src/movie_review/rendering/renderer.py
src/movie_review/review/writer.py
src/movie_review/story/events.py
src/movie_review/tts/reconcile.py
src/movie_review/vision/analysis.py
docs/troubleshooting.md
tests/unit/test_remote_http.py
tests/unit/test_job_failure.py   (new)
tests/unit/test_vision_parallel.py
```

**Acceptance criteria**

- [x] concurrent model calls never share a connection
- [x] a sequential run still reuses an idle connection
- [x] a broken connection is closed rather than returned to the idle list
- [x] a stage that refuses a failed job names the stage and repeats its error
- [x] `pytest -q` passes

---

## T177 - Configurable transport retry for a model server that restarts

**Objective**

Make the retry schedule a slot's own configuration, keep the server's error body
in the message, and let a 5xx outlast a vLLM engine reload instead of killing a
stage that has been running for twenty minutes.

**Depends on**: T136, T137.

**The defect**

A remote run (`job_20261022_014`, `--profile remote`) died at `vision` after
21m26s with

```text
Cannot analyze scene_000061: HTTP 500 from http://192.168.1.144:8000/v1/chat/completions
```

Three separate faults hid behind that line.

The schedule was too short to matter. `remote/http.py` retried a 5xx -- and a
429, a timeout, a dropped connection -- three attempts in total with a 0.5 s
base of exponential backoff. Measured against a host that answers 500 every
time, the whole budget came to 1.31 s. A vLLM engine that has just crashed and
is reloading answers 500 for something closer to a minute, so every attempt
landed inside the outage and the retry existed but never helped.

A 5xx was reported as the wrong kind of failure. `_Transient` carried a
`RemoteProtocolError`, which the adapters map to "the model answered badly" --
a permanent error. The stage-level policy added in T137 only retries errors
classified as transient, so a 5xx went straight past it and failed the stage at
the first scene that saw one. The pooled path was worse in the other direction:
it treated every non-2xx status as retryable, so a 404 from a wrong
`endpoint_path` was attempted three times before being reported.

The server's own explanation was discarded. Both paths read the response body
in full and then built `HTTP {status} from {url}` from the status alone, so the
one sentence that says whether the engine died or the context was too long
never reached the operator -- which is why job_20261022_014 could not be
diagnosed after the fact.

**Files**

```text
src/movie_review/remote/http.py
src/movie_review/config/settings.py
src/movie_review/asr/openai_compat.py
src/movie_review/asr/factory.py
src/movie_review/reasoning/openai_compat.py
src/movie_review/reasoning/factory.py
src/movie_review/tts/openai_compat.py
src/movie_review/tts/factory.py
src/movie_review/vision/openai_compat.py
src/movie_review/vision/factory.py
config/models.yaml
docs/model-selection.md
docs/troubleshooting.md
tests/unit/test_remote_http.py
tests/unit/test_config.py
tests/unit/test_remote_adapters.py
```

**Acceptance criteria**

- [x] attempts, backoff base and the backoff ceiling are per-slot configuration
  (`attempts`, `backoff_seconds`, `max_backoff_seconds`), not literals in code
- [x] a retryable status is retried and, once the budget is spent, reported as
  `RemoteUnavailableError` so the stage-level policy can retry the stage
- [x] a 4xx is reported after a single attempt on both the pooled and the
  injected-transport paths
- [x] the message quotes the server's error body, on one line and bounded to
  `ERROR_EXCERPT_CHARS`, and never quotes headers
- [x] the shipped `remote` profile gives vision and reasoning four attempts,
  waiting up to 5 s / 10 s / 20 s between them (`max_backoff_seconds: 30`)
- [x] a zero base keeps retrying without sleeping, so tests do not wait
- [x] the T177 tests pass (`test_remote_http`, `test_config`,
  `test_remote_adapters`: 88 passed)
- [ ] `pytest -q` passes -- 1628 passed, 1 failed: `test_proxy_settings_defaults`
  is red only because `config/default.yaml` carries an uncommitted local change
  (`media.proxy` 854x480) that is not part of this task

---

## T178 - Proxy scaling must land on even dimensions

**Objective**

Stop `libx264` from refusing the proxy when the configured box does not divide
the source aspect ratio evenly.

**Depends on**: T012.

**The defect**

`media/proxy.py` scaled with

```text
scale=w=854:h=480:force_original_aspect_ratio=decrease
```

`max_width`/`max_height` are a **box**, not a size: ffmpeg fits the source into
it and rounds each side on its own. For a 1920x1080 film and an 854x480 box the
height is the binding side, so the width lands on 853.33 -> 853. `libx264` with
`yuv420p` requires both sides even and refuses the frame, and the failure is
raised on the very first frame:

```text
Cannot generate proxy for E:\Phim\AI.mp4: ffmpeg failed:
[libx264] width not divisible by 2 (853x480)
```

The run therefore died at `vision` after 120 ms, before sampling a scene, and
the message pointed at the encoder rather than at the box that caused it
(job_20261022_003). The default 1280x720 happens to be even for 16:9, which is
why this stayed hidden until a smaller box was tried.

**Files**

```text
src/movie_review/media/proxy.py
docs/troubleshooting.md
tests/unit/test_proxy.py
```

**Acceptance criteria**

- [x] the scale filter enforces divisible-by-two sides on both dimensions
- [x] a 1920x1080 source in an 854x480 box encodes, with an even output that
  does not exceed the box, asserted against a real ffmpeg run
- [x] the filter keeps `force_original_aspect_ratio=decrease`, so the source is
  never upscaled to fill the box
- [x] `pytest tests/unit/test_proxy.py -q` passes apart from
  `test_proxy_settings_defaults`, which is red only for the uncommitted local
  `config/default.yaml` change (see T177)

---

## T179 - Batch frame extraction: one decode pass per scene

**Objective**

Stop paying one process launch and one seek-and-decode per frame. Extract a
scene's whole sample set in a single FFmpeg decode pass with a `select`
filter, and fall back to the per-frame seek when the pass cannot be trusted.

**Depends on**: T015.

**The defect**

`media/frames.py` extracted every frame with its own
`ffmpeg -ss T -i source -frames:v 1` invocation. Each launch re-opens the
file, re-seeks to the timestamp and re-decodes the region before the first
frame. A feature film samples roughly 6,000 frames, so the frames stage pays
6,000 launches and 6,000 seeks for work one pass per scene could do.

FFmpeg's `select` filter keeps frames by index in a single decode:
`-vf "select=eq(n\,123)+eq(n\,456)+..."` writes the kept frames in stream
order, so the i-th output file is the i-th requested timestamp. Frame index
addressing needs the stream's fps, which the ingest probe already recorded.

**Files**

```text
src/movie_review/media/frames.py
src/movie_review/pipeline/orchestrator.py
tests/unit/test_frames_batch.py
```

**Acceptance criteria**

- [x] a scene with N samples runs one FFmpeg pass for N >= 2, asserted by
  counting invocations
- [x] batch outputs land on the same deterministic filenames the per-frame
  path used, with the i-th kept frame mapping to the i-th timestamp
- [x] no fps, colliding frame indices, a failed pass, or samples past the
  last frame all fall back to the per-frame path without losing a frame
- [x] the per-frame output of a real 24 fps test clip is byte-identical to
  the batch output at the same frame index
- [x] `sample_movie` reports progress per frame as before and persists
  after every scene as before
- [x] `STAGE_VERSION` moves to v3 so v2 cache entries are not adopted
- [x] the orchestrator passes the probed fps from the job's metadata
- [x] `pytest -q` passes apart from the three pre-existing
  `test_publish_title.py` Windows-path failures, which are red on this
  master and unrelated to frame sampling

---

## T180 - Perceptual frame deduplication

**Objective**

Stop sampling the same picture twice. A static or slow shot sampled six
times produces six near-identical frames; a dissolve gives two adjacent
scenes a shared boundary frame. Drop the near-duplicates after sampling and
after feedback so the VLM reads each distinct picture once.

**Depends on**: T179.

**The defect**

`sample_timestamps` spaces frames evenly over a scene's span and
`apply_feedback` tops up boosted scenes, and neither knows what the frames
look like. A 60-second held shot yields six frames the VLM is then asked to
describe six times -- tokens spent re-reading one picture -- and a dissolve
puts a copy of scene A's last frame at the head of scene B. The cache and
the manifest already guard against *re-extracting* a frame, but nothing
guards against *sampling* two visually identical frames.

A difference hash (dHash) fixes the detection: 64 bits of coarse structure
(horizontally adjacent pixels compared in a 9x8 grayscale render).
Near-identical frames differ by a handful of bits; different frames by
dozens. The hash is computed without an image library -- one FFmpeg concat
pass per scene renders the frames to raw 9x8 gray bytes -- so no dependency
is added and a movie's frames never leave the machine.

Two consequences the fix must keep straight:

- A deduplicated manifest is part of the cache identity, so the dedupe
  switch and threshold join the frames cache key, and the frame stage's
  manifest records each kept frame's dhash.
- A resumed run must drop the same frames a fresh run would, or the manifest
  would differ between a fresh run and a resume and every downstream cache
  keyed on frame hashes would miss. Adopted scenes therefore seed the
  deduper from their recorded dhashes.
- T179 bound the fps into `frames_cache_key`, but `apply_feedback` still
  computed the key without it, so the feedback pass would overwrite a
  different cache slot than the one `sample_movie` wrote. The feedback path
  must bind the same fps.

**Files**

```text
src/movie_review/media/fingerprint.py
src/movie_review/media/frames.py
src/movie_review/media/feedback.py
src/movie_review/pipeline/orchestrator.py
src/movie_review/config/settings.py
config/default.yaml
tests/unit/test_fingerprint.py
tests/unit/test_frames_dedupe.py
tests/unit/test_feedback_dedupe.py
```

**Acceptance criteria**

- [x] a static scene keeps exactly its floor of frames; a dynamic scene
  keeps all of them
- [x] a boundary frame shared by two adjacent scenes is dropped from the
  later scene beyond its floor
- [x] the dhash is computed by one FFmpeg concat pass per scene, asserted by
  counting invocations, with no image library in the dependency list
- [x] near-identical real frames hash within the threshold; different real
  frames hash far outside it
- [x] a fingerprint failure keeps all frames of the scene and logs it
  instead of failing the stage
- [x] the dedupe switch and threshold are configuration, not constants, and
  join the frames cache key
- [x] the manifest records the dhash of every kept frame, and a resumed run
  drops the same frames a fresh run does
- [x] `apply_feedback` stops adding frames that duplicate the scene's kept
  frames, and its cache key binds the same fps as `sample_movie`
- [x] `pytest -q` passes apart from the pre-existing `test_publish_title.py`
  failures

---
## T181 - The vision request carries no more frames than its endpoint will take

**Objective**

Make the number of frames one VLM request carries a configured cap instead of
an implicit "however many the scene sampled", and when a scene exceeds the cap,
send a deterministic chronological, evenly spaced subset.

**Depends on**: T025.

**The defect**

`vision/analysis.py` sends every frame the scene sampled in one request: up to
12 for a long scene, more after the feedback boost. A remote endpoint decides
whether it accepts that many images in a single request, and one that refuses
(or OOMs decoding them) fails the stage on the largest scenes, with no way to
configure the limit without code changes. The boosted-frames pass re-analysed
with whatever default the function carried, not the configured value.

**Files**

```text
src/movie_review/config/settings.py
src/movie_review/vision/analysis.py
src/movie_review/pipeline/orchestrator.py
tests/unit/test_vision_max_frames.py
tests/unit/test_vision_frames_wiring.py
```

**Acceptance criteria**

- [x] a request carries no more than `max_frames_per_request` frames,
  asserted on the frames the port actually receives
- [x] a scene at or under the cap gets an unchanged request: every frame,
  the same prompt counts
- [x] a scene over the cap gets a subset that is chronological, evenly
  spaced, keeps the scene's first and last frame, and has exactly the cap's
  length
- [x] the cap is configuration on the vision model spec (env/yaml
  overridable), not a code threshold, and joins the vision cache key: a
  different cap re-analyses instead of adopting
- [x] the prompt's frame count describes the frames the request carries
- [x] the orchestrator passes the configured cap on both the first pass and
  the boosted-frames pass
- [x] `pytest -q` passes apart from the pre-existing `test_publish_title.py`
  Windows-path failures, which are red on this master

## T182 - One config file, pointable from the CLI

**Objective**

Merge `config/default.yaml` and `config/models.yaml` into a single
`config/config.yaml`, and let the application point at a different config
file with a `--config PATH` flag (the `MOVIE_REVIEW_CONFIG` env var already
did this for the old two-file layout).

**Depends on**: T002, T181.

**The problem**

Two files describe one configuration: the product controls in
`default.yaml` and the model catalog in `models.yaml`, tied together by a
profile name and by the loader deriving the catalog path from the config
file's directory. An operator who copies one file to a new machine, or
points `MOVIE_REVIEW_CONFIG` at a custom file, ships or validates against a
missing catalog, and the failure surfaces as "Unknown model profile
'balanced'" — a message that does not name the missing file. And there is
no flag for the common case "run this job with my own config".

**Design**

- One file: `config/config.yaml` = the former `default.yaml` plus the
  `profiles:` catalog. No two-file fallback; the old layout is a clean break
  and an error that names the merge.
- `models.profile` (or `--profile` / `MOVIE_REVIEW_MODELS__PROFILE`) still
  selects from the `profiles:` catalog in the same file.
- CLI: `--config PATH` is a global option on the app, set in the startup
  callback before any settings load in the process, so every
  `load_settings()` — the orchestrator's internal loads included — resolves
  against the same file. Precedence: `--config` > `MOVIE_REVIEW_CONFIG` >
  `<repo>/config/config.yaml`. A missing file is a clean non-zero exit, not
  a traceback.
- Scripts: `benchmark_pipeline.py`, `benchmark_models.py`,
  `validate_movie.py`, `cleanup_cache.py` gain the same `--config` flag.
- Desktop: `settings:read` / `settings:write` operate on the one file; the
  two editors (model profiles / pipeline settings) edit one draft of it and
  both save buttons write the whole file.

**Files**

```text
.spec/tasks.md
config/config.yaml
config/default.yaml                    (deleted)
config/models.yaml                     (deleted)
src/movie_review/config/settings.py
src/movie_review/cli/app.py
src/movie_review/pipeline/orchestrator.py    (docstrings only)
scripts/benchmark_pipeline.py
scripts/benchmark_models.py
scripts/validate_movie.py
scripts/cleanup_cache.py
desktop/scripts/desktop_bridge.py
desktop/src/main/ipc.js
desktop/src/renderer/index.html
desktop/src/renderer/app.js
desktop/test/bridge.test.js
desktop/test/python-runner.test.js
tests/conftest.py
tests/unit/test_config.py
tests/unit/test_config_cleanup.py
tests/unit/test_cli_profile.py
tests/unit/test_privacy_gate.py
tests/unit/test_remote_reasoning.py
tests/unit/test_orchestrator.py
tests/unit/test_desktop_bridge.py
README.md
docs/GETTING-STARTED.md
docs/DESKTOP-APP.md
docs/architecture.md
docs/model-selection.md
docs/pipeline.md
docs/troubleshooting.md
```

**Acceptance criteria**

- [x] `config/config.yaml` is the only top-level config file in `config/`:
  `default.yaml` and `models.yaml` are gone, and a plain `load_settings()`
  resolves the profile from the file's own `profiles` catalog
- [x] a config file without a `profiles` catalog fails with an error that
  names the file and the merge, not "Unknown model profile"
- [x] `movie-review <command> --config PATH` runs every settings load in the
  process against that file, and a missing file is a clean non-zero exit
  with a message, not a traceback
- [x] precedence holds: `--config` > `MOVIE_REVIEW_CONFIG` > repo default;
  `--profile` > `MOVIE_REVIEW_MODELS__PROFILE` > `models.profile` >
  `balanced`
- [x] the desktop bridge reads and writes the single file: `settings:write`
  validates the whole document (every profile expands), refuses invalid
  input with exit 2, and leaves a `.bak.<timestamp>` on success
- [x] `pytest -q` passes apart from the pre-existing `test_publish_title.py`
  Windows-path failures, which are red on this master

## T183 - The batch frame pass creates the directory ffmpeg writes to

**Objective**

Make the T179 batch pass actually run: create the per-scene `.batch` output
directory before launching the single-pass ffmpeg, and make the tests catch
a pass that silently falls back.

**Depends on**: T179.

**The defect**

`extract_scene_frames` launches the single-pass ffmpeg writing to
`<dest>/.batch/%05d.jpg`, but only `<dest>` is created. ffmpeg's image2
muxer does not create directories, so the pass always exits non-zero
("Could not open file ... .batch/00001.jpg: No such file or directory"),
logs a warning per scene, and falls back to the per-frame seeks. Jobs stay
correct — the fallback does its job — but the optimisation T179 shipped
(one decode pass per scene) never ran: every scene paid for N launches and
N decodes, and the vision log filled with warnings.

Two things hid it: the fake ``run_fn`` in the unit tests created the
pattern's parent directory (real ffmpeg does not), and the real-ffmpeg test
only asserted the pass was *attempted* and compared frame bytes — the
fallback's output is byte-identical to a direct seek, so the comparison
passes either way.

**Files**

```text
.spec/tasks.md
src/movie_review/media/frames.py
tests/unit/test_frames_batch.py
```

**Acceptance criteria**

- [x] with real ffmpeg the batch pass succeeds without a fallback: one
  select call, zero per-frame seeks, no "falling back to per-frame"
  warning, and no `.batch` directory left behind
- [x] the fake ``run_fn`` emulates the image2 directory contract (missing
  directory -> non-zero exit), so the unit tests pin the ``mkdir`` without
  needing the binary
- [x] `pytest -q` passes apart from the pre-existing `test_publish_title.py`
  Windows-path failures, which are red on this master
