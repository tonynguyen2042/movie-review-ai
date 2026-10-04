# AGENTS.md — movie-review-ai

## Mission

Implement the local-first, evidence-backed movie-to-review pipeline.

## Authority

```text
constitution.md
  >
spec.md
  >
plan.md
  >
tasks.md
  >
AGENTS.md
```

## Mandatory Workflow

### STEP 1 — Identify task

Read the exact task in `tasks.md`.

Record:

- task ID
- objective
- dependencies
- expected files
- acceptance criteria
- expected tests

Work on one task at a time.

### STEP 2 — Create task branch

Every task MUST have its own branch.

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

If the worktree has unrelated changes, STOP.

### STEP 3 — Inspect repository

Inspect:

- repository tree
- current branch
- worktree
- related implementation
- tests
- contracts
- task dependencies

### STEP 4 — Search before creating

Search for existing:

- classes
- functions
- schemas
- CLI commands
- tests
- utilities

Never create duplicate files:

```text
foo_new.py
foo_v2.py
foo_final.py
foo_fixed.py
```

### STEP 5 — Identify contracts

Before coding, identify:

- domain contracts
- schemas
- ports
- stage inputs/outputs
- cache identity
- persistence
- failure behavior
- CLI behavior

### STEP 6 — Define milestones

Split a non-trivial task into meaningful milestones.

Example:

```text
T005
 M1 schema
 M2 repository
 M3 tests
```

Do not create artificial commits for trivial changes.

### STEP 7 — Implement smallest complete milestone

Implement only the requested milestone.

Avoid:

- unrelated refactoring
- architecture replacement
- unnecessary dependencies
- premature UI
- premature vector DB
- model/runtime switching without approval

### STEP 8 — Test milestone

Run targeted tests.

```bash
pytest <affected-tests> -q
git diff --check
```

### STEP 9 — Commit milestone

After targeted tests pass:

```bash
git status --short
git diff --check
git add <task-related-files>
git commit -m "feat(T005): add SQLite schema"
```

Commit format:

```text
<type>(<task-id>): <imperative summary>
```

Allowed types:

```text
feat
fix
test
refactor
docs
chore
perf
```

Never commit known failing tests.

Never use blind:

```bash
git add .
```

### STEP 10 — Repeat milestones

For each milestone:

```text
implement
→ targeted tests
→ diff check
→ commit
```

### STEP 11 — Full validation

Before task completion:

```bash
pytest -q
```

must pass.

Also run when configured:

```bash
ruff check .
ruff format --check .
mypy .
```

Do not claim a check passed unless the command actually succeeds.

### STEP 12 — Validate acceptance

Verify every acceptance criterion in `tasks.md`.

Code compiling is not sufficient.

### STEP 13 — Update task state

Only after all required validation passes:

```text
[ ] → [x]
```

Commit the state update.

### STEP 14 — Push branch

```bash
git push -u origin task/T005-sqlite-repository
```

### STEP 15 — Create PR

Automatically create a PR targeting `master` when repository PR tooling is available.

Preferred GitHub CLI:

```bash
gh pr create \
  --base master \
  --head task/T005-sqlite-repository \
  --title "feat(T005): add SQLite repository" \
  --body-file .git/pr-body.md
```

PR body must contain:

```markdown
## Task

T005

## Summary

...

## Milestones

- commit 1
- commit 2
- commit 3

## Validation

- [x] pytest -q
- [x] ruff check .
- [x] ruff format --check .
- [x] mypy .

## Acceptance Criteria

- [x] ...

## Architecture Impact

None / details

## Risks

None / details
```

Never fabricate a PR URL.

If PR tooling or credentials are unavailable:

```text
PR: NOT CREATED — <exact reason>
```

### STEP 16 — Do not auto-merge

PR creation is automatic.

PR merge is NOT automatic unless explicitly authorized.

Default:

```text
branch
→ commits
→ tests
→ [x]
→ push
→ PR → master
→ STOP
```

## Pipeline Stage Rule

Every stage follows:

```text
validate input
→ cache lookup
→ execute
→ validate output
→ persist
→ metrics
→ complete
```

Stages must be idempotent.

## Domain Isolation

Domain must not import:

- MLX
- FFmpeg
- SQLite
- Typer
- model SDKs

## Structured AI Output

AI output must be:

```text
schema-constrained
→ parsed
→ validated
→ normalized
→ persisted
```

Never use free-form model prose as a canonical contract.

## Model Abstraction

Use ports/adapters for:

- ASR
- diarization
- VLM
- reasoning LLM
- TTS

## Prompt Versioning

Prompts belong under:

```text
config/prompts/
```

Prompt changes invalidate dependent AI artifacts.

## Resource Awareness

Target:

```text
Apple Silicon
128 GB unified memory
```

Prefer sequential model residency.

Support:

```text
OOM detection
→ model release
→ cache cleanup
→ reduced workload
→ retry
```

## Error Handling

Never:

```python
except Exception:
    pass
```

Errors must be logged, classified, and surfaced.

## CLI

CLI must:

- return non-zero on failure
- support `--help`
- expose useful logs
- avoid hidden destructive operations

## Configuration

Do not hard-code:

- model names
- paths
- duration
- WPM
- quality thresholds
- memory limits
- prompt versions

## Cache

Cache identity should include relevant:

- input hash
- dependency artifact hashes
- stage version
- model/version
- prompt version
- generation config

## Review Writer

Must not invent:

- dialogue
- scenes
- relationships
- deaths
- plot facts
- chronology

Unsupported claims must be removed or marked:

```text
INSUFFICIENT_EVIDENCE
```

Interpretation/opinion must be explicitly represented.

## Copyright

Never claim that fixed clip duration or percentage is automatically legally safe.

## Stop Conditions

STOP if:

- dependency is missing
- schema conflicts with canonical schema
- architecture change is unapproved
- model output repeatedly violates schema
- data corruption appears
- duplicate retry artifacts appear
- contracts conflict
- user changes are at risk
- master changed and synchronization is ambiguous
- PR credentials/tooling are unavailable

## Anti-loop Guard

Before editing:

```text
Task:
Files:
Reason:
Expected change:
```

After editing:

```text
inspect diff
→ targeted test
→ verify progress
```

If the same file is modified more than 3 times for the same task without measurable progress:

```text
STOP
```

Do not create another duplicate file.

## Completion Report

Use:

```text
Task: Txxx
Branch: task/Txxx-...
Status: DONE
Tests: PASS
Lint: PASS
Type check: PASS
Milestones:
  - <commit>
  - <commit>
PR: <URL>
```

If PR was not created:

```text
PR: NOT CREATED — <specific reason>
```

## Definition of Done

A task is DONE only when:

- implementation exists
- contracts are valid
- targeted tests pass
- full test suite passes
- configured lint/type checks pass
- acceptance criteria pass
- task state is `[x]`
- milestones are committed
- branch is pushed
- PR to `master` is created

No silent exceptions.
