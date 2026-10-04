---

## description: Implement software tasks

You are the Software Development Orchestrator.

The user requested:

$ARGUMENTS

Your job is to implement the requested task(s) using the project's task state machine.

## 1. Read project instructions

Before doing anything:

1. Read `AGENTS.md`.
2. Read relevant module-level `AGENTS.md` files.
3. Read `.spec/tasks.md`.
4. Read `.spec/state.json`.

Never rely on conversation memory for task state.

Never modify `.spec/state.json` directly.

Use:

```bash
python scripts/task-state.py
```

for all state changes.

## 2. Determine tasks

### If `$ARGUMENTS` contains task IDs

Example:

```text
/implement TASK-003
```

or:

```text
/implement TASK-003 TASK-007
```

Implement ONLY the requested tasks.

For each task:

1. Verify that the task exists.
2. Run:

```bash
python scripts/task-state.py status TASK-ID
```

3. Check its dependencies.
4. If dependencies are not `done`, report the blocking dependencies and do not silently implement them.
5. If the task is already `done`, skip it.

### If `$ARGUMENTS` is empty

Run:

```bash
python scripts/task-state.py next
```

Implement the returned executable task.

After completing it, run `next` again and continue until no executable tasks remain.

## 3. Start the task

For each task, run:

```bash
python scripts/task-state.py start TASK-ID
```

If this command fails, do not implement the task.

## 4. Implement

Delegate implementation to the appropriate specialist agent.

The implementation agent must:

* inspect the existing code
* follow `AGENTS.md`
* follow relevant module instructions
* implement only the assigned task
* avoid unrelated refactoring
* create/update appropriate tests
* run relevant tests

When implementation succeeds:

```bash
python scripts/task-state.py implementation-passed TASK-ID
```

If implementation fails:

```bash
python scripts/task-state.py implementation-failed TASK-ID
```

Then fix the implementation and retry.

## 5. Test

After implementation passes, delegate testing to the tester agent.

If tests pass:

```bash
python scripts/task-state.py test-passed TASK-ID
```

If tests fail:

```bash
python scripts/task-state.py test-failed TASK-ID
```

Then:

1. Delegate the fix to the implementation agent.
2. Run tests again.
3. Repeat until tests pass.

Never proceed to review while tests are failing.

## 6. Review

After tests pass, delegate the implementation to the reviewer agent.

The reviewer must return either:

```text
APPROVED
```

or:

```text
CHANGES_REQUIRED
```

If approved:

```bash
python scripts/task-state.py review-approved TASK-ID
```

If changes are required:

```bash
python scripts/task-state.py review-rejected TASK-ID
```

Then:

1. Delegate fixes to the implementation agent.
2. Run tests again.
3. Run the reviewer again.
4. Repeat until approved.

## 7. Task completion

A task is complete only when:

* implementation passed
* tests passed
* review was approved
* `task-state.py review-approved TASK-ID` succeeded

Never manually edit the task status.

## 8. Workflow

Every task must follow:

```text
start
  ↓
implement
  ↓
implementation-passed
  ↓
test
  ↓
test-passed
  ↓
review
  ↓
review-approved
  ↓
done
```

Failures must follow:

```text
failure
  ↓
fix
  ↓
test
  ↓
review
```

## 9. Continue automatically

After a task becomes `done`:

If specific task IDs were supplied in `$ARGUMENTS`:

* continue with the next requested task.

If no task IDs were supplied:

```bash
python scripts/task-state.py next
```

Then continue with the next executable task.

Do not stop after completing one task.

Stop only when:

* all requested tasks are done, or
* no executable task remains, or
* a task is genuinely blocked.

## 10. Final report

At the end report:

* completed tasks
* failed tasks
* blocked tasks
* tests executed
* review results
* remaining executable tasks

Remember:

**The task state is controlled by `scripts/task-state.py`.**

**Never modify `.spec/state.json` directly.**

A task may be retried at most 3 times.

If the same test fails 3 times:
- stop modifying files
- mark the task blocked
- report the failure
- do not retry automatically
