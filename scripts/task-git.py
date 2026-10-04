#!/usr/bin/env python3
"""Enforce the movie-review-ai task Git lifecycle.

Examples:
  python scripts/task-git.py start T001 bootstrap-python-project
  python scripts/task-git.py verify T001
  python scripts/task-git.py finish T001 feat "bootstrap Python project"
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(args))
    return subprocess.run(args, cwd=ROOT, text=True, check=check)


def branch_name(task_id: str, slug: str) -> str:
    return f"task/{task_id}-{slug}"


def current_branch() -> str:
    return run("git", "branch", "--show-current").stdout.strip()


def start(task_id: str, slug: str) -> None:
    if current_branch() != "master":
        raise SystemExit("Refusing to start: current branch is not master.")
    if run("git", "status", "--porcelain").stdout.strip():
        raise SystemExit("Refusing to start: working tree is not clean.")

    run("git", "fetch", "--prune")
    run("git", "checkout", "master")
    run("git", "pull", "--ff-only", "origin", "master")
    run("git", "checkout", "-b", branch_name(task_id, slug))


def verify(task_id: str) -> None:
    branch = current_branch()
    if not branch.startswith(f"task/{task_id}-"):
        raise SystemExit(f"Wrong branch: {branch}")
    run("git", "diff", "--check")
    run("pytest", "-q")


def finish(task_id: str, commit_type: str, summary: str) -> None:
    branch = current_branch()
    if not branch.startswith(f"task/{task_id}-"):
        raise SystemExit(f"Wrong branch: {branch}")

    run("git", "diff", "--check")
    run("pytest", "-q")

    if run("git", "status", "--porcelain").stdout.strip():
        raise SystemExit(
            "Working tree is not clean. Commit the final task-state update first."
        )

    run("git", "push", "-u", "origin", branch)

    body = f"""## Task

{task_id}

## Summary

{summary}

## Validation

- [x] pytest -q
- [x] git diff --check

## Merge

PR creation is automatic; merge is intentionally manual.
"""
    body_file = ROOT / ".git" / "pr-body.md"
    body_file.write_text(body, encoding="utf-8")

    run(
        "gh",
        "pr",
        "create",
        "--base",
        "master",
        "--head",
        branch,
        "--title",
        f"{commit_type}({task_id}): {summary}",
        "--body-file",
        str(body_file),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("start")
    p.add_argument("task_id")
    p.add_argument("slug")

    p = sub.add_parser("verify")
    p.add_argument("task_id")

    p = sub.add_parser("finish")
    p.add_argument("task_id")
    p.add_argument("commit_type")
    p.add_argument("summary")

    args = parser.parse_args()

    if args.command == "start":
        start(args.task_id, args.slug)
    elif args.command == "verify":
        verify(args.task_id)
    else:
        finish(args.task_id, args.commit_type, args.summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
