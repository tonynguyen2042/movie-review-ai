#!/usr/bin/env python3

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_FILE = ROOT / ".spec" / "tasks.yaml"
STATE_FILE = ROOT / ".spec" / "state.json"


def now():
    return datetime.now(UTC).isoformat()


def load_state():
    if not STATE_FILE.exists():
        print(f"ERROR: {STATE_FILE} does not exist", file=sys.stderr)
        sys.exit(1)

    with STATE_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    tmp = STATE_FILE.with_suffix(".json.tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")

    tmp.replace(STATE_FILE)


def get_task(state, task_id):
    task = state.get("tasks", {}).get(task_id)

    if task is None:
        print(f"ERROR: Unknown task: {task_id}", file=sys.stderr)
        sys.exit(1)

    return task


def dependencies_done(state, task):
    return all(
        state["tasks"].get(dep, {}).get("status") == "done" for dep in task.get("depends_on", [])
    )


def cmd_next(state):
    for task_id, task in state["tasks"].items():
        if task.get("status") != "pending":
            continue

        if dependencies_done(state, task):
            print(task_id)
            return

    print("NONE")


def cmd_start(state, task_id):
    task = get_task(state, task_id)

    if task["status"] == "done":
        print(f"ERROR: {task_id} is already done")
        sys.exit(1)

    if not dependencies_done(state, task):
        blocked = [
            dep
            for dep in task.get("depends_on", [])
            if state["tasks"].get(dep, {}).get("status") != "done"
        ]

        print(
            f"ERROR: {task_id} is blocked by: {', '.join(blocked)}",
            file=sys.stderr,
        )
        sys.exit(1)

    task["status"] = "in_progress"
    task["attempts"] = task.get("attempts", 0) + 1
    task["started_at"] = now()
    task["implementation"] = "pending"
    task["tests"] = "pending"
    task["review"] = "pending"

    save_state(state)

    print(f"STARTED {task_id}")


def cmd_implementation_passed(state, task_id):
    task = get_task(state, task_id)

    task["implementation"] = "passed"

    if task["status"] == "in_progress":
        task["status"] = "testing"

    task["updated_at"] = now()

    save_state(state)

    print(f"IMPLEMENTATION_PASSED {task_id}")


def cmd_implementation_failed(state, task_id):
    task = get_task(state, task_id)

    task["implementation"] = "failed"
    task["status"] = "fixing"
    task["updated_at"] = now()

    save_state(state)

    print(f"IMPLEMENTATION_FAILED {task_id}")


def cmd_test_passed(state, task_id):
    task = get_task(state, task_id)

    if task.get("implementation") != "passed":
        print(
            f"ERROR: Cannot pass tests before implementation passes: {task_id}",
            file=sys.stderr,
        )
        sys.exit(1)

    task["tests"] = "passed"
    task["status"] = "review"
    task["updated_at"] = now()

    save_state(state)

    print(f"TEST_PASSED {task_id}")


def cmd_test_failed(state, task_id):
    task = get_task(state, task_id)

    task["tests"] = "failed"
    task["status"] = "fixing"
    task["updated_at"] = now()

    save_state(state)

    print(f"TEST_FAILED {task_id}")


def cmd_review_approved(state, task_id):
    task = get_task(state, task_id)

    if task.get("tests") != "passed":
        print(
            f"ERROR: Cannot approve review before tests pass: {task_id}",
            file=sys.stderr,
        )
        sys.exit(1)

    task["review"] = "approved"
    task["status"] = "done"
    task["completed_at"] = now()
    task["updated_at"] = now()

    save_state(state)

    print(f"DONE {task_id}")


def cmd_review_rejected(state, task_id):
    task = get_task(state, task_id)

    task["review"] = "changes_required"
    task["status"] = "fixing"
    task["updated_at"] = now()

    save_state(state)

    print(f"REVIEW_FAILED {task_id}")


def cmd_status(state, task_id=None):
    if task_id:
        task = get_task(state, task_id)

        print(json.dumps({"id": task_id, **task}, indent=2))

        return

    print(json.dumps(state, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(description="Manage OpenCode task execution state.")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("next")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("start")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("implementation-passed")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_implementation_passed)

    p = sub.add_parser("implementation-failed")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_implementation_failed)

    p = sub.add_parser("test-passed")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_test_passed)

    p = sub.add_parser("test-failed")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_test_failed)

    p = sub.add_parser("review-approved")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_review_approved)

    p = sub.add_parser("review-rejected")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_review_rejected)

    p = sub.add_parser("status")
    p.add_argument("task_id", nargs="?")
    p.set_defaults(func=cmd_status)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    state = load_state()

    if hasattr(args, "task_id"):
        args.func(state, args.task_id)
    else:
        args.func(state)


if __name__ == "__main__":
    main()
