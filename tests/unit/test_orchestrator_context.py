"""The stage closures must not rebuild the context by hand.

T172. `pipeline/orchestrator.py` built a `StageContext` from six fields by
hand in ten stage closures. The `PipelineContext` subclass already carried
every field one needs, and its own docstring said the stage contract only
needed the context fields — but the closures discarded it and rebuilt the
thing, so a new field had to be added in eleven places.
"""

from __future__ import annotations

import ast
from pathlib import Path

from movie_review.pipeline.orchestrator import PipelineContext

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "src" / "movie_review" / "pipeline" / "orchestrator.py"


def _stage_closures() -> list[ast.FunctionDef]:
    """The closures that build a stage's context."""
    tree = ast.parse(ORCHESTRATOR.read_text(encoding="utf-8"))
    closures: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.endswith("_fn"):
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "StageContext"
            ):
                closures.append(node)
    return closures


def test_no_stage_closure_builds_a_context_by_hand() -> None:
    """Ten closures rebuilt the same eleven lines."""
    offenders = sorted({node.name for node in _stage_closures()})
    assert not offenders, f"these stages still build the context by hand: {offenders}"


def test_the_context_carries_everything_a_stage_needs() -> None:
    """The method exists so the closures do not have to."""
    import inspect

    source = inspect.getsource(PipelineContext.stage_context)
    for field in ("job_id", "jobs_dir", "conn", "manager", "cache", "settings"):
        assert field in source, f"{field} is not carried"


def test_the_method_returns_a_plain_stage_context() -> None:
    """The return type is declared, so the method is typed."""
    import typing

    from movie_review.pipeline.context import StageContext

    hints = typing.get_type_hints(PipelineContext.stage_context)
    assert hints["return"] is StageContext
