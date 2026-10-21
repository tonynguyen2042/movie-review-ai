# Fix Plan — movie-review-ai

**Created:** 2026-10-21
**Baseline:** `master` @ `ca68061575a65b1f9aa78213fdc3283d582bde50`
**Source:** four independent audits (correctness, performance, spec-gap, test-coverage)
plus direct verification by the reviewer.

## 0. Progress

| Wave | State | Tasks |
|---|---|---|
| 0 — Gate repair | **done** | T113, T114, T115 |
| 1 — P0 blockers | **done** | T116, T117, T118 |
| 2 — P1 correctness | 4 of 13 | T120, T121, T122, T123, T124, T126, T127 |
| 3 — Performance | 0 of 10 | — |
| 4 — Missing wiring | 0 of 11 | — |
| 5 — Spec gaps | 0 of 7 | — |
| 6 — Test infrastructure | 0 of 9 | — |
| 7 — Docs and cleanup | 0 of 4 | — |

**14 of 60 tasks merged.** Every one landed as its own branch, its own PR and
its own merge, and every one passed `pytest -q`, `ruff check .`,
`ruff format --check .` and `mypy .` before it merged.

The suite has gone from **1214 passed / 7 failed** to **1255 passed / 0
failed**, and `mypy .` from 107 errors to none.

The three P0 blockers are gone: the render stage can now read a manifest,
the render manifest is timed by the narration that was synthesized, and the
quality gate can fail a job.

## 1. Rules this plan follows

From `.spec/constitution.md` §4 and `AGENTS.md`:

- one task = one branch = `task/<task-id>-<short-description>`
- branch starts from current `master`
- milestone commits, format `<type>(<task-id>): <summary>`
- before `[x]`: `pytest -q`, `ruff check .`, `ruff format --check .`, `mypy .`
  all exit `0`
- push branch, create PR → `master`
- **merge only after the checks pass and the user has authorised it** (authorised
  2026-10-21 for this plan)

## 1. Corrections to the audit output

| Audit claim | Correction |
|---|---|
| "`mypy .` fails with 107 errors" | `mypy src` **passes** (161 files, clean). The 107 errors are in `tests/` and `scripts/` only. `AGENTS.md` §STEP 11 literally says `mypy .`, so those 107 are still in scope — as **T114**. |
| "7 docs tests fail" | Environment-dependent, and the cause is **two** distinct defects, not one encoding bug: (a) the parent decodes the child's pipe with the locale codec, (b) the regex requires an ASCII `\|` but Rich emits `│` (U+2502) under UTF-8 mode. Python 3.15 enables UTF-8 mode by default, so (b) becomes a universal break. See **T115**. |
| "quality gate always passes" | Confirmed by direct reading; additionally `quality/{coverage,timeline,characters,visual}.py`, `build_quality_report` and `validate_render` are never called from `src/`. See **T118**. |
| "render stage raises `KeyError: 'manifest'`" | Reproduced by executing the real code path. See **T116**. |

## 2. Why the defects survived

Root cause of the whole class, established by the test-coverage audit:

- `tests/unit/test_orchestrator.py` monkeypatches `_get_stage_function` wholesale
  → **16 of 19 stage closures never execute in any test**
- no CI, no coverage gate, no `tests/conftest.py`, `tests/pipeline/` empty
- 13 production modules are complete but called by nothing

So a module-level-quality codebase with zero wiring coverage. Waves 0 and 6
repair the gate itself; the middle waves repair the wiring.

## 3. Task index

60 tasks, 8 waves. `Wave 0` must land first: until it does, no task can satisfy
`AGENTS.md` STEP 11, because `mypy .` fails and 7 tests fail.

### Wave 0 — Gate repair (prerequisite for every other task)

| ID | Type | Title | Branch |
|---|---|---|---|
| T113 | chore | ignore runtime artifacts | `task/T113-ignore-runtime-artifacts` | **DONE** |
| T114 | chore | `mypy .` green | `task/T114-mypy-strict-clean` | **DONE** |
| T115 | fix | docs test: encoding + Rich separator | `task/T115-docs-test-encoding` | **DONE** |

### Wave 1 — P0 blockers (pipeline cannot produce a video)

| ID | Type | Title | Branch |
|---|---|---|---|
| T116 | fix | render stage reads the flat manifest | `task/T116-render-manifest-shape` | **DONE** |
| T117 | fix | render manifest uses measured narration | `task/T117-measured-narration-timings` | **DONE** |
| T118 | fix | quality gate computes real metrics | `task/T118-quality-gate-metrics` | **DONE** |

### Wave 2 — P1 correctness (silently wrong output)

| ID | Type | Title | Branch |
|---|---|---|---|
| T119 | fix | CLI options reach the pipeline | `task/T119-cli-options-plumbing` | **DONE** |
| T120 | fix | configured WPM replaces hard-coded 150 | `task/T120-configured-wpm` | **DONE** |
| T121 | fix | fact-check misquote detection | `task/T121-misquote-any-all` | **DONE** |
| T122 | fix | render-manifest stage name | `task/T122-render-manifest-stage-name` | **DONE** |
| T123 | fix | resume validates the stage name | `task/T123-resume-stage-validation` | **DONE** |
| T124 | fix | publish title path leak | `task/T124-publish-title-stem` | **DONE** |
| T125 | fix | unload adapters on cache hits | `task/T125-unload-on-cache-hit` | **DONE** |
| T126 | fix | language reaches local Whisper | `task/T126-whisper-language` | **DONE** |
| T127 | fix | close SQLite connections | `task/T127-close-sqlite-connections` | **DONE** |
| T128 | fix | job-ID allocation race | `task/T128-job-id-race` | **DONE** |
| T129 | fix | scene detection idempotency | `task/T129-scene-detection-idempotent` | **DONE** |
| T130 | fix | cache keys bind every input | `task/T130-cache-key-inputs` | **DONE** |
| T131 | fix | CLI exit codes and reporter cleanup | `task/T131-cli-exit-codes` | **DONE** |

### Wave 3 — Performance (measured; 2 h film)

| ID | Type | Title | Branch |
|---|---|---|---|
| T132 | perf | retrieval EvidenceIndex — O(S²)→O(S) | `task/T132-retrieval-evidence-index` | **DONE** |
| T133 | perf | frames manifest O(N²) | `task/T133-frames-manifest-quadratic` | **DONE** |
| T134 | perf | SQLite WAL + indexes | `task/T134-sqlite-wal-indexes` | **DONE** |
| T135 | perf | chunked ASR upload | `task/T135-asr-chunked-upload` | **DONE** |
| T136 | perf | HTTP reuse + transport retry | `task/T136-http-pooling-retry` | **DONE** |
| T137 | perf | stage-level retry policy | `task/T137-stage-retry-policy` | **DONE** |
| T138 | perf | parallelise the vision stage | `task/T138-parallel-vision-stage` | **DONE** |
| T139 | perf | parallelise the events stage | `task/T139-parallel-events-stage` | **DONE** |
| T140 | perf | cut prompt token duplication | `task/T140-prompt-token-duplication` | **DONE** |
| T141 | perf | remaining hot paths | `task/T141-hot-path-cleanups` | **DONE** |

### Wave 4 — Missing wiring (written, never called)

| ID | Type | Title | Branch |
|---|---|---|---|
| T142 | feat | verify stage: claims→fact-check→repair | `task/T142-verify-stage` |
| T143 | feat | subtitles stage | `task/T143-subtitles-stage` |
| T144 | feat | diarization + speaker linking | `task/T144-diarization-stage` |
| T145 | feat | story graph relationships | `task/T145-story-graph` |
| T146 | feat | adaptive frame sampling feedback | `task/T146-sampling-feedback` |
| T147 | feat | music bed + ducking | `task/T147-music-ducking` |
| T148 | feat | thumbnail generation | `task/T148-thumbnail-generation` |
| T149 | feat | OOM recovery wired in | `task/T149-oom-recovery-wiring` |
| T150 | feat | privacy.cloud_ai enforced | `task/T150-privacy-cloud-ai` |
| T151 | feat | output set (md, manifest, --output) | `task/T151-output-set` |
| T152 | feat | prompt registry matches reality | `task/T152-prompt-registry` |

### Wave 5 — Spec gaps (README §49/§52/§53/§56/§74/§77/§96)

| ID | Type | Title | Branch |
|---|---|---|---|
| T153 | feat | CLI read-only commands | `task/T153-cli-read-commands` |
| T154 | feat | CLI benchmark command | `task/T154-cli-benchmark` |
| T155 | feat | CLI flags | `task/T155-cli-flags` |
| T156 | feat | model_runs + token usage | `task/T156-model-runs` |
| T157 | feat | missing DB tables | `task/T157-missing-db-tables` |
| T158 | feat | JSON Schemas + validation | `task/T158-json-schemas` |
| T159 | feat | second-pass critic model | `task/T159-critic-model` |

### Wave 6 — Test infrastructure

| ID | Type | Title | Branch |
|---|---|---|---|
| T160 | test | CI + coverage gate | `task/T160-ci-coverage-gate` |
| T161 | test | root conftest + de-duplicate helpers | `task/T161-root-conftest` |
| T162 | test | markers, strict config, timeout | `task/T162-pytest-markers` |
| T163 | test | end-to-end pipeline test | `task/T163-pipeline-e2e-test` |
| T164 | test | golden baseline | `task/T164-golden-baseline` |
| T165 | test | remote/http.py direct tests | `task/T165-remote-http-tests` |
| T166 | test | path-traversal guard tests | `task/T166-path-guard-tests` |
| T167 | test | TTS chunk-id stability | `task/T167-tts-chunk-id-stability` |
| T168 | test | de-flaky timing tests | `task/T168-deflake-timing-tests` |

### Wave 7 — Docs and cleanup

| ID | Type | Title | Branch |
|---|---|---|---|
| T169 | docs | the 5 missing `docs/` files | `task/T169-missing-docs` |
| T170 | docs | the 4 missing `scripts/` files | `task/T170-missing-scripts` |
| T171 | chore | LICENSE + config cleanup | `task/T171-license-config-cleanup` |
| T172 | refactor | orchestrator context duplication | `task/T172-orchestrator-context-refactor` |

## 4. Dependency graph

```text
T113 ─┬─> T114 ─┬─> T115
      │         │
      │         └─> T160 (CI) ──> T161 ──> T162 ──> T163 ──> T164
      │
      ├─> T116 ──> T117 ──> T118 ──> T142 ──> T143
      │                    │
      │                    └─> T151
      ├─> T119 ──> T120
      ├─> T121
      ├─> T122 ──> T123
      ├─> T124
      ├─> T125
      ├─> T126
      ├─> T127 ──> T128
      ├─> T129
      ├─> T130
      ├─> T131
      ├─> T132
      ├─> T133
      ├─> T134
      ├─> T135
      ├─> T136 ──> T137
      ├─> T138 ──> T139 ──> T140 ──> T141
      ├─> T144 ──> T145
      ├─> T146
      ├─> T147
      ├─> T148
      ├─> T149
      ├─> T150
      ├─> T152
      ├─> T153 ──> T154
      ├─> T155
      ├─> T156 ──> T157
      ├─> T158
      ├─> T159
      ├─> T165 ──> T166
      ├─> T167
      ├─> T168
      ├─> T169 ──> T170
      └─> T171 ──> T172
```

Waves are the execution order. Within a wave, tasks with no edge between
them are independent and may be prepared in any order; each is still its own
branch and its own PR.

## 5. Per-task execution procedure

Every task, without exception:

```text
1. git checkout master && git pull --ff-only origin master
2. git checkout -b task/<id>-<slug>
3. implement (smallest complete milestone)
4. targeted tests  ->  pytest <affected> -q
5. git diff --check
6. commit: <type>(<id>): <imperative summary>
7. full gate:  pytest -q && ruff check . && ruff format --check . && mypy .
8. update .spec/tasks.md acceptance criteria to [x] and .spec/state.json
9. commit the state update
10. git push -u origin task/<id>-<slug>
11. create PR -> master   (github MCP; `gh` is not installed on this host)
12. merge PR -> master    (authorised 2026-10-21; only after step 7 passed)
13. delete the local branch
```

## 6. Stop conditions (from `AGENTS.md`)

STOP and report if:

- `pytest -q` fails for a reason unrelated to the task
- a fix requires a schema change that conflicts with the canonical schema
- a fix needs an architecture change that was not approved
- the same file is edited more than 3 times without measurable progress
- `master` moved and the synchronisation is ambiguous
- PR credentials are unavailable (the GitHub MCP server must be authenticated)
